"""
Local PDF Financial Statement Extractor
========================================
Uses pdfplumber word-position-based extraction — NO API KEY REQUIRED.

Strategy:
  1. Scan every page for financial statement headers (keyword match)
  2. Detect year-column x-boundaries from the "March 31, XXXX" header words
  3. Reconstruct each row: label (left zone) + FY1 value + FY2 value
  4. Map row labels → financial model fields via regex patterns
  5. Convert units (Millions / Crores / Billions / Thousands)

Handles:
  - Multi-page statements (BS assets + liabilities on separate pages)
  - Bracket negatives:  (10,229.1) → -10229.1
  - Split-word artefacts: "C ost" → "Cost"
  - Section headers with no values
  - Notes column (ignored)
  - Both Standalone and Consolidated (prefer Consolidated)
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

import pdfplumber

from models.company_data import ExtractionMetadata, FinancialData
from models.financial_statements import BalanceSheet, CashFlowStatement, IncomeStatement
from utils.logger import get_logger

log = get_logger()

# ── Types ─────────────────────────────────────────────────────────────────────
Row = Dict[str, Optional[float]]          # {"label": str, "y1": float|None, "y2": float|None}
RawTable = List[Dict]                     # list of Row dicts


# ── Number helpers ─────────────────────────────────────────────────────────────

def _parse_number(text: str) -> Optional[float]:
    """
    Parse Indian-format numbers from PDF text.
    Examples: '484,968.5' → 484968.5
              '(10,229.1)' → -10229.1
              '-' / '—' / 'Nil' → None
    """
    if not text:
        return None
    text = text.strip()
    if text in ('-', '—', '–', '', 'nil', 'Nil', 'NIL', 'N/A', 'n/a'):
        return None
    negative = text.startswith('(') and text.endswith(')')
    cleaned = re.sub(r'[(),\s₹]', '', text)   # strip brackets, commas handled below
    cleaned = cleaned.replace(',', '')
    try:
        val = float(cleaned)
        return -val if negative else val
    except ValueError:
        return None


def _unit_to_crores(value: Optional[float], from_unit: str) -> Optional[float]:
    """Convert any unit → Crores. (1 Crore = 10 Million = 0.01 Billion)"""
    if value is None:
        return None
    factors = {
        'Crores': 1.0,
        'Millions': 0.1,         # 1 Crore = 10 Million
        'Billions': 100.0,        # 1 Billion = 100 Crores
        'Thousands': 0.0001,      # 1 Crore = 10,000 Thousand
    }
    return value * factors.get(from_unit, 1.0)


def _convert(value: Optional[float], from_unit: str, to_unit: str) -> Optional[float]:
    if value is None:
        return None
    in_crores = _unit_to_crores(value, from_unit)
    if in_crores is None:
        return None
    factors = {
        'Crores': 1.0,
        'Millions': 10.0,
        'Billions': 0.01,
        'Thousands': 10000.0,
    }
    return in_crores * factors.get(to_unit, 1.0)


# ── Page-level extraction ──────────────────────────────────────────────────────

def _detect_unit(words: List[dict]) -> str:
    """Detect the reporting unit from page header text."""
    header_text = ' '.join(w['text'] for w in words if w['top'] < 140).lower()
    if 'million' in header_text:
        return 'Millions'
    if 'billion' in header_text:
        return 'Billions'
    if 'thousand' in header_text or 'lakh' in header_text:
        return 'Thousands'
    return 'Crores'


def _detect_columns(words: List[dict]) -> Optional[Tuple[float, float, float]]:
    """
    Find (label_max_x, year1_right_x, year2_right_x) from header.
    Looks for 4-digit year words in the top 180 points of the page.
    Returns None if no year headers found.
    """
    year_words = [
        w for w in words
        if re.fullmatch(r'20\d\d', w['text']) and w['top'] < 200
    ]
    if not year_words:
        return None

    # Sort by x1 (right edge); usually two year columns
    year_words.sort(key=lambda w: w['x1'])
    if len(year_words) >= 2:
        col1_right = year_words[-2]['x1']  # earlier year or same year (left col)
        col2_right = year_words[-1]['x1']  # later year (right col)
    else:
        col1_right = year_words[-1]['x1']
        col2_right = col1_right           # single year

    # Label column ends well before the first number column
    # (numbers are right-aligned, so subtract ~80 pts from right edge)
    label_max = col1_right - 80
    return label_max, col1_right, col2_right


def _extract_years_from_header(words: List[dict]) -> Tuple[Optional[int], Optional[int]]:
    """Return (year1, year2) from the page header."""
    year_words = [
        w for w in words
        if re.fullmatch(r'20\d\d', w['text']) and w['top'] < 200
    ]
    year_words.sort(key=lambda w: w['x1'])
    years = [int(w['text']) for w in year_words]
    y1 = years[-2] if len(years) >= 2 else (years[0] if years else None)
    y2 = years[-1] if len(years) >= 1 else None
    return y1, y2


def _group_rows(words: List[dict], label_max: float,
                col1_right: float, col2_right: float,
                tolerance: float = 3.0) -> List[dict]:
    """
    Group words into rows by their vertical position (top), then assign
    each word to label / year1 / year2 column.

    Returns list of {"label": str, "raw1": str, "raw2": str}
    """
    if not words:
        return []

    # Sort words by top, then by x0
    words = sorted(words, key=lambda w: (round(w['top'] / tolerance), w['x0']))

    rows: List[dict] = []
    current_top: Optional[float] = None
    current_row: dict = {"label_parts": [], "raw1": None, "raw2": None}

    def flush():
        nonlocal current_row
        if current_row["label_parts"] or current_row["raw1"] or current_row["raw2"]:
            rows.append(current_row)
        current_row = {"label_parts": [], "raw1": None, "raw2": None}

    for w in words:
        top = w['top']
        text = w['text']

        # New row?
        if current_top is None or abs(top - current_top) > tolerance:
            flush()
            current_top = top

        x0 = w['x0']
        x1 = w['x1']

        # Assign to column
        if x0 < label_max:
            current_row["label_parts"].append(text)
        elif abs(x1 - col1_right) <= 22:
            current_row["raw1"] = text
        elif abs(x1 - col2_right) <= 22:
            current_row["raw2"] = text
        # else: notes column or other — skip

    flush()

    # Build final rows, joining label parts and fixing split-word artefacts
    result = []
    for r in rows:
        label = _clean_label(' '.join(r['label_parts']))
        if not label and not r['raw1'] and not r['raw2']:
            continue
        result.append({
            "label":  label,
            "raw1":   r['raw1'],
            "raw2":   r['raw2'],
        })
    return result


def _clean_label(label: str) -> str:
    """
    Fix common PDF artefacts in label text:
      - "C ost" → "Cost"   (single-char + space + rest, gap caused by font)
      - Extra whitespace
      - Strip leading roman numerals / letters like "(i)", "(a)", "(1)"
    """
    # Fix single-char split words: "C ost" → "Cost"
    label = re.sub(r'(?<!\w)([A-Z]) ([a-z])', r'\1\2', label)
    # Normalise whitespace
    label = re.sub(r'\s+', ' ', label).strip()
    # Strip leading list markers: (i), (ii), (a), (b), (1), (2) …
    label = re.sub(r'^\([a-z0-9ivxIVX]+\)\s*', '', label)
    # Strip leading roman numerals
    label = re.sub(r'^[ivxIVX]+\.\s*', '', label)
    return label


# ── Page scanner ──────────────────────────────────────────────────────────────

_STMT_PATTERNS = {
    "pl":  [r"statement of profit and loss", r"profit and loss account",
            r"statement of profit & loss"],
    "bs":  [r"balance sheet"],
    "cf":  [r"statement of cash flow", r"cash flow statement"],
}

_SCOPE_PATTERNS = {
    "consolidated": [r"consolidated"],
    "standalone":   [r"standalone", r"separate"],
}


def _page_score(text: str, patterns: List[str]) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in patterns)


def scan_for_statement_pages(pdf, target_years: Optional[List[int]] = None
                             ) -> Dict[str, List[int]]:
    """
    Returns dict mapping statement type → list of 1-based page numbers
    where that statement appears, filtered to match target_years.
    Priority: consolidated > standalone.
    """
    results: Dict[str, Dict[str, List[int]]] = {
        "consolidated": {"pl": [], "bs": [], "cf": []},
        "standalone":   {"pl": [], "bs": [], "cf": []},
    }

    # Also store page years for later filtering
    page_years: Dict[int, List[int]] = {}   # 1-based page → detected years

    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        low  = text.lower()
        pg_num = i + 1

        # Must have real numbers to be a data page
        if not re.search(r'\d{3,}', text):
            continue

        # Detect years on this page from header (top portion)
        words = page.extract_words() or []
        hdr_words = [w for w in words if w['top'] < 200]
        yrs = [int(w['text']) for w in hdr_words
               if re.fullmatch(r'20\d\d', w['text'])]
        page_years[pg_num] = list(set(yrs))

        # Determine scope
        scope = None
        for sc, pats in _SCOPE_PATTERNS.items():
            if _page_score(low, pats):
                scope = sc
                break
        if scope is None:
            continue

        # Determine statement type (only major statement headers)
        for stmt, pats in _STMT_PATTERNS.items():
            if _page_score(low, pats):
                results[scope][stmt].append(pg_num)
                break

    def _filter_by_years(pages: List[int]) -> List[int]:
        """Keep only pages whose detected years overlap with target_years."""
        if not target_years:
            return pages
        return [p for p in pages
                if any(y in (target_years or []) for y in page_years.get(p, []))]

    def _add_continuation(pages: List[int], stmt_type: str) -> List[int]:
        """
        For each page, also include the immediately following page if it
        looks like a continuation (same statement header, same years).
        This handles BS split across assets page + liabilities page.
        """
        expanded = list(pages)
        for p in pages:
            nxt = p + 1
            if nxt in page_years and nxt not in expanded:
                nxt_text = (pdf.pages[nxt - 1].extract_text() or "").lower()
                # Include if it has the same statement keyword and matching years
                if _page_score(nxt_text, _STMT_PATTERNS.get(stmt_type, [])):
                    if not target_years or any(
                        y in target_years for y in page_years.get(nxt, [])
                    ):
                        expanded.append(nxt)
        return sorted(set(expanded))

    # Prefer consolidated; fall back to standalone
    final: Dict[str, List[int]] = {}
    for stmt in ("pl", "bs", "cf"):
        pages = results["consolidated"][stmt] or results["standalone"][stmt]
        pages = _filter_by_years(pages)
        pages = _add_continuation(pages, stmt)
        if pages:
            # Keep up to 4 pages per statement type
            final[stmt] = pages[:4]

    return final


# ── Multi-page table extractor ─────────────────────────────────────────────────

def extract_table_from_pages(pdf, page_nums: List[int]) -> Tuple[RawTable, str, int, int]:
    """
    Extract rows from one or more consecutive pages of the same statement.
    Returns (rows, detected_unit, year1, year2).
    """
    all_rows: RawTable = []
    detected_unit = "Crores"
    year1: Optional[int] = None
    year2: Optional[int] = None

    for pg_num in page_nums:
        page = pdf.pages[pg_num - 1]
        words = page.extract_words(keep_blank_chars=False,
                                   x_tolerance=2, y_tolerance=3)
        if not words:
            continue

        # Detect columns & unit — only lock in values from the FIRST successful page
        col_info = _detect_columns(words)
        if col_info is not None:
            new_label_max, new_col1, new_col2 = col_info
            if year1 is None:
                # First successful page: lock in unit, columns, and years
                detected_unit = _detect_unit(words)
                label_max, col1_right, col2_right = new_label_max, new_col1, new_col2
                y1, y2 = _extract_years_from_header(words)
                year1 = y1
                year2 = y2
            else:
                # Continuation page: update column positions but keep unit from page 1
                label_max, col1_right, col2_right = new_label_max, new_col1, new_col2
        elif year1 is None:
            # First page must have a detectable header
            log.warning(f"Could not detect columns on page {pg_num} — skipping")
            continue
        # else: continuation page without header → reuse previous col_info

        # Skip header rows (top < 170) on continuation pages
        if len(all_rows) > 0:
            data_words = [w for w in words if w['top'] > 165]
        else:
            data_words = words

        rows = _group_rows(data_words, label_max, col1_right, col2_right)
        all_rows.extend(rows)

    return all_rows, detected_unit, year1 or 0, year2 or 0


# ── Field mappers ──────────────────────────────────────────────────────────────

def _norm(label: str) -> str:
    """Normalise for pattern matching: lowercase, collapse spaces, strip punct."""
    return re.sub(r'[^a-z0-9 ]', ' ', label.lower())


def _match(label: str, patterns: List[str]) -> bool:
    n = _norm(label)
    return any(re.search(p, n) for p in patterns)


def _first(rows: RawTable, patterns: List[str],
           from_unit: str, to_unit: str) -> Optional[float]:
    """Return the FY1 (current year) value of the first row matching patterns."""
    for r in rows:
        if r['label'] and _match(r['label'], patterns):
            return _convert(_parse_number(r['raw1']), from_unit, to_unit)
    return None


def _first2(rows: RawTable, patterns: List[str],
            from_unit: str, to_unit: str) -> Tuple[Optional[float], Optional[float]]:
    """Return (FY1, FY2) values of the first matching row."""
    for r in rows:
        if r['label'] and _match(r['label'], patterns):
            v1 = _convert(_parse_number(r['raw1']), from_unit, to_unit)
            v2 = _convert(_parse_number(r['raw2']), from_unit, to_unit)
            return v1, v2
    return None, None


def _rows_for_year(rows: RawTable, year_col: int,
                   from_unit: str, to_unit: str) -> Dict[str, Optional[float]]:
    """Build {normalised_label → value} dict for one year."""
    out = {}
    for r in rows:
        if not r['label']:
            continue
        raw = r['raw1'] if year_col == 1 else r['raw2']
        val = _convert(_parse_number(raw), from_unit, to_unit)
        out[_norm(r['label'])] = val
    return out


# ── Income Statement mapper ────────────────────────────────────────────────────

_IS_FIELDS = {
    "revenue":                  [r"revenue from operations", r"net sales", r"net revenue"],
    "other_income":             [r"other income"],
    "cost_of_goods_sold":       [r"cost of materials consumed", r"cost of goods sold",
                                 r"raw material", r"cost of material"],
    "purchases_trading":        [r"purchases of stock.in.trade", r"purchases of traded goods",
                                 r"purchase of stock"],
    "changes_in_inventory":     [r"changes in inventor", r"change in stock",
                                 r"increase decrease in inventor"],
    "employee_expenses":        [r"employee benefit", r"employee cost", r"staff cost",
                                 r"remuneration"],
    "finance_costs":            [r"finance cost", r"interest expense", r"finance charge",
                                 r"financial cost"],
    "depreciation_amortization":[r"depreciation and amortis", r"depreciation and amortiz",
                                 r"depreciation depletion"],
    "other_expenses":           [r"other expense"],
    "total_expenses":           [r"total expense"],
    "profit_before_tax":        [r"profit before tax", r"earnings before tax", r"\bpbt\b"],
    "tax_expense":              [r"tax expense", r"income tax expense", r"total tax"],
    "current_tax":              [r"current tax"],
    "deferred_tax":             [r"deferred tax"],
    "pat":                      [r"profit for the year", r"profit after tax",
                                 r"net profit", r"profit for period",
                                 r"total comprehensive income"],
}


def map_income_statement(rows: RawTable, from_unit: str, to_unit: str,
                         fiscal_year: int) -> IncomeStatement:
    g = lambda *pats: _first(rows, list(pats), from_unit, to_unit)

    revenue      = g(*_IS_FIELDS["revenue"])
    other_income = g(*_IS_FIELDS["other_income"])
    cogs         = g(*_IS_FIELDS["cost_of_goods_sold"])
    purchases    = g(*_IS_FIELDS["purchases_trading"])
    inv_chg      = g(*_IS_FIELDS["changes_in_inventory"])
    employee     = g(*_IS_FIELDS["employee_expenses"])
    finance      = g(*_IS_FIELDS["finance_costs"])
    depn         = g(*_IS_FIELDS["depreciation_amortization"])
    other_exp    = g(*_IS_FIELDS["other_expenses"])
    pbt          = g(*_IS_FIELDS["profit_before_tax"])
    tax          = g(*_IS_FIELDS["tax_expense"])
    pat          = g(*_IS_FIELDS["pat"])

    # Gross profit = Revenue - COGS - inventory change - purchases
    gross_profit: Optional[float] = None
    if revenue is not None:
        deductions = sum(x for x in [cogs, purchases, inv_chg] if x is not None)
        gross_profit = revenue - deductions if deductions else None

    # EBITDA = PBT + finance + depreciation  (bottom-up build)
    ebitda: Optional[float] = None
    if pbt is not None:
        add_backs = sum(x for x in [finance, depn] if x is not None)
        ebitda = pbt + add_backs if add_backs else None

    # EBIT = EBITDA - depreciation
    ebit: Optional[float] = None
    if ebitda is not None and depn is not None:
        ebit = ebitda - depn

    return IncomeStatement(
        fiscal_year=fiscal_year,
        revenue=revenue,
        other_income=other_income,
        gross_profit=gross_profit,
        cogs=cogs,
        employee_expenses=employee,
        depreciation_amortization=depn,
        ebitda=ebitda,
        ebit=ebit,
        interest_expense=finance,
        other_operating_expenses=other_exp,
        pbt=pbt,
        tax_expense=tax,
        pat=pat,
        extraction_confidence=0.88,
    )


# ── Balance Sheet mapper ───────────────────────────────────────────────────────

_BS_FIELDS = {
    # Assets
    "ppe":                  [r"property plant and equipment", r"tangible asset",
                             r"fixed asset", r"property  plant"],
    "capital_wip":          [r"capital work.in.progress", r"cwip"],
    "goodwill":             [r"\bgoodwill\b"],
    "intangible_assets":    [r"other intangible", r"intangible asset"],
    "right_of_use":         [r"right.of.use", r"rou asset"],
    "non_current_invest":   [r"financial asset.*investment", r"long.term investment",
                             r"non.current.*investment"],
    "deferred_tax_assets":  [r"deferred tax asset"],
    "other_nc_assets":      [r"other non.current asset"],
    "inventories":          [r"\binventor", r"\bstock\b"],
    "trade_receivables":    [r"trade receivable", r"debtor", r"accounts receivable"],
    "cash":                 [r"cash and cash equivalent"],
    "bank_balances":        [r"bank balance"],
    "current_invest":       [r"current investment", r"short.term investment"],
    "other_current_assets": [r"other current asset"],
    "total_nc_assets":      [r"total non.current asset"],
    "total_current_assets": [r"total current asset"],
    "total_assets":         [r"total asset"],
    # Equity
    "share_capital":        [r"equity share capital", r"share capital"],
    "other_equity":         [r"other equity", r"reserves and surplus"],
    "nci":                  [r"non.controlling interest", r"minority interest"],
    "total_equity":         [r"total equity"],
    # Liabilities
    "lt_borrowings":        [r"borrowing"],   # detected by section context below
    "lease_nc":             [r"lease liabilit"],
    "deferred_tax_liab":    [r"deferred tax liabilit"],
    "other_nc_liab":        [r"other non.current liabilit"],
    "total_nc_liab":        [r"total non.current liabilit"],
    "st_borrowings":        [r"borrowing"],   # detected by section context
    "trade_payables":       [r"trade payable", r"creditor", r"accounts payable"],
    "other_current_liab":   [r"other current liabilit"],
    "total_current_liab":   [r"total current liabilit"],
    "total_liab":           [r"total liabilit"],
    "total_equity_liab":    [r"total equity and liabilit", r"total liabilit.*equity"],
}


def map_balance_sheet(rows: RawTable, from_unit: str, to_unit: str,
                      fiscal_year: int) -> BalanceSheet:
    # Section context: track if we're in assets / non-current-liab / current-liab
    section = "unknown"
    nc_liab_section = False
    curr_liab_section = False

    # Values dict by normalised label
    vals: Dict[str, Optional[float]] = {}
    for r in rows:
        lbl = r['label']
        if not lbl:
            continue
        n = _norm(lbl)
        # Detect section changes
        if re.search(r'\bassets\b', n):
            section = "assets"
            nc_liab_section = False; curr_liab_section = False
        elif re.search(r'non.current liabilit', n):
            section = "nc_liab"
            nc_liab_section = True; curr_liab_section = False
        elif re.search(r'current liabilit', n) and 'non' not in n:
            section = "curr_liab"
            nc_liab_section = False; curr_liab_section = True
        vals[n] = _convert(_parse_number(r['raw1']), from_unit, to_unit)

    def g(*patterns: str) -> Optional[float]:
        for pat in patterns:
            for key, val in vals.items():
                if re.search(pat, key) and val is not None:
                    return val
        return None

    def g_section(section_check: str, *patterns: str) -> Optional[float]:
        """Match a pattern only within rows that were in a specific section."""
        in_correct_section = False
        for r in rows:
            lbl = r['label']
            if not lbl:
                continue
            n = _norm(lbl)
            # update section tracker
            if re.search(r'\bassets\b', n):
                in_correct_section = (section_check == "assets")
            elif re.search(r'non.current liabilit', n):
                in_correct_section = (section_check == "nc_liab")
            elif re.search(r'current liabilit', n) and 'non' not in n:
                in_correct_section = (section_check == "curr_liab")

            if in_correct_section:
                for pat in patterns:
                    if re.search(pat, n):
                        val = _convert(_parse_number(r['raw1']), from_unit, to_unit)
                        if val is not None:
                            return val
        return None

    # Assets
    ppe             = g(r"property plant and equipment", r"tangible asset", r"fixed asset")
    cwip            = g(r"capital work.in.progress")
    goodwill        = g(r"\bgoodwill\b")
    intangibles     = g(r"other intangible", r"intangible asset")
    rou             = g(r"right.of.use", r"rou asset")
    nc_invest       = g(r"non.current.*investment", r"long.term investment")
    dta             = g(r"deferred tax asset")
    other_nc_assets = g(r"other non.current asset")
    total_nc_assets = g(r"total non.current asset")
    inventories     = g(r"\binventor")
    receivables     = g(r"trade receivable", r"debtor")
    cash            = g(r"cash and cash equivalent")
    bank_bal        = g(r"bank balance other", r"other bank balance")
    curr_invest     = g(r"current investment", r"short.term investment")
    other_curr_ass  = g(r"other current asset")
    total_curr_ass  = g(r"total current asset")
    total_assets    = g(r"total asset")

    # Equity
    share_capital   = g(r"equity share capital", r"share capital")
    other_equity    = g(r"other equity", r"reserves and surplus")
    nci             = g(r"non.controlling interest", r"minority interest")
    total_equity    = g(r"total equity")

    # Liabilities (section-aware)
    lt_borrow       = g_section("nc_liab",    r"\bborrowing")
    st_borrow       = g_section("curr_liab",  r"\bborrowing")
    lease_nc        = g_section("nc_liab",    r"lease liabilit")
    lease_curr      = g_section("curr_liab",  r"lease liabilit")
    dt_liab         = g(r"deferred tax liabilit")
    other_nc_liab   = g(r"other non.current liabilit")
    total_nc_liab   = g(r"total non.current liabilit")
    trade_payables  = g(r"trade payable", r"creditor")
    other_curr_liab = g(r"other current liabilit")
    total_curr_liab = g(r"total current liabilit")

    # Net debt computation
    total_debt: Optional[float] = None
    if lt_borrow is not None or st_borrow is not None:
        total_debt = (lt_borrow or 0) + (st_borrow or 0)

    short_invest = curr_invest
    net_debt: Optional[float] = None
    if total_debt is not None and cash is not None:
        net_debt = total_debt - cash - (bank_bal or 0) - (short_invest or 0)

    return BalanceSheet(
        fiscal_year=fiscal_year,
        # Non-current assets (using actual model field names)
        net_fixed_assets=ppe,
        capital_wip=cwip,
        goodwill=goodwill,
        intangible_assets=intangibles,
        long_term_investments=nc_invest,
        deferred_tax_assets=dta,
        other_non_current_assets=other_nc_assets,
        total_non_current_assets=total_nc_assets,
        # Current assets
        inventory=inventories,
        accounts_receivable=receivables,
        cash_and_equivalents=cash,
        short_term_investments=curr_invest or bank_bal,
        other_current_assets=other_curr_ass,
        total_current_assets=total_curr_ass,
        total_assets=total_assets,
        # Equity
        share_capital=share_capital,
        reserves_and_surplus=other_equity,
        minority_interest=nci,
        total_equity=total_equity,
        # Non-current liabilities
        long_term_debt=lt_borrow,
        deferred_tax_liabilities=dt_liab,
        other_non_current_liabilities=other_nc_liab,
        total_non_current_liabilities=total_nc_liab,
        # Current liabilities
        short_term_borrowings=st_borrow,
        accounts_payable=trade_payables,
        other_current_liabilities=other_curr_liab,
        total_current_liabilities=total_curr_liab,
        # Totals
        total_liabilities_and_equity=total_assets,
        extraction_confidence=0.88,
    )


# ── Cash Flow mapper ───────────────────────────────────────────────────────────

def map_cash_flow(rows: RawTable, from_unit: str, to_unit: str,
                  fiscal_year: int) -> CashFlowStatement:
    def g(*patterns: str) -> Optional[float]:
        return _first(rows, list(patterns), from_unit, to_unit)

    pbt         = g(r"profit before tax")
    depn        = g(r"depreciation and amortis", r"depreciation and amortiz")
    finance_adj = g(r"finance cost")          # adjustment in OCF
    cfo         = g(r"net cash.*from operating", r"net cash generated from operating",
                    r"net cash.*operating activit")
    capex       = g(r"purchase of property", r"additions to.*property",
                    r"capital expenditure", r"purchase.*ppe",
                    r"acquisition.*property plant")
    asset_sale  = g(r"proceeds.*sale.*property", r"proceeds from disposal")
    buy_invest  = g(r"purchase.*investment", r"acquisition.*investment")
    sell_invest = g(r"proceeds.*sale.*investment", r"proceeds.*investment")
    int_recv    = g(r"interest received", r"interest income received")
    div_recv    = g(r"dividend received")
    cfi         = g(r"net cash.*from investing", r"net cash used in investing",
                    r"net cash.*investing activit")
    proc_borrow = g(r"proceeds from borrowing")
    repay_borrow= g(r"repayment of borrowing")
    div_paid    = g(r"dividend paid", r"dividends paid")
    int_paid    = g(r"interest paid", r"finance cost paid",
                    r"repayment.*principal.*lease")
    cff         = g(r"net cash.*from financing", r"net cash used in financing",
                    r"net cash.*financing activit")
    open_cash   = g(r"cash.*beginning", r"opening.*cash", r"cash.*at.*beginning")
    close_cash  = g(r"cash.*end", r"closing.*cash", r"cash.*at.*end")

    # FCF = CFO - Capex
    fcf: Optional[float] = None
    if cfo is not None and capex is not None:
        fcf = cfo + capex     # capex is typically negative in CF statement

    net_change: Optional[float] = None
    if open_cash is not None and close_cash is not None:
        net_change = close_cash - open_cash

    return CashFlowStatement(
        fiscal_year=fiscal_year,
        net_income=pbt,                         # closest approximation before tax
        depreciation_amortization=depn,
        cash_from_operations=cfo,
        capex=capex,
        proceeds_from_asset_sales=asset_sale,
        cash_from_investing=cfi,
        debt_raised=proc_borrow,
        debt_repaid=repay_borrow,
        dividends_paid=div_paid,
        cash_from_financing=cff,
        net_change_in_cash=net_change,
        opening_cash=open_cash,
        closing_cash=close_cash,
        free_cash_flow=fcf,
        extraction_confidence=0.86,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_local(
    path: str,
    company_name: str,
    fiscal_years: List[int],
    currency: str = "INR",
    unit: str = "Crores",
) -> FinancialData:
    """
    Extract all three financial statements from a PDF using local word-position parsing.
    No API key required. Returns a FinancialData object.
    """
    log.info(f"[LocalPDF] Opening {path}")
    income_statements: List[IncomeStatement] = []
    balance_sheets:    List[BalanceSheet]    = []
    cash_flows:        List[CashFlowStatement] = []

    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        log.info(f"[LocalPDF] {total} pages — scanning for financial statements…")

        page_map = scan_for_statement_pages(pdf, target_years=fiscal_years)
        log.info(f"[LocalPDF] Statement pages found: {page_map}")

        # ── Income Statement ──────────────────────────────────────────────
        if page_map.get("pl"):
            rows, from_unit, y1, y2 = extract_table_from_pages(pdf, page_map["pl"])
            log.info(f"[LocalPDF] P&L: {len(rows)} rows, unit={from_unit}, years={y1},{y2}")
            for yr, col, py in [(y1, 1, fiscal_years), (y2, 2, fiscal_years)]:
                if yr and (not fiscal_years or yr in fiscal_years):
                    stmt_rows = [{**r, "raw1": r["raw1"] if col == 1 else r["raw2"]} for r in rows]
                    is_ = map_income_statement(stmt_rows, from_unit, unit, yr)
                    income_statements.append(is_)

        # ── Balance Sheet ─────────────────────────────────────────────────
        if page_map.get("bs"):
            rows, from_unit, y1, y2 = extract_table_from_pages(pdf, page_map["bs"])
            log.info(f"[LocalPDF] BS:  {len(rows)} rows, unit={from_unit}, years={y1},{y2}")
            for yr, col in [(y1, 1), (y2, 2)]:
                if yr and (not fiscal_years or yr in fiscal_years):
                    stmt_rows = [{**r, "raw1": r["raw1"] if col == 1 else r["raw2"]} for r in rows]
                    bs_ = map_balance_sheet(stmt_rows, from_unit, unit, yr)
                    balance_sheets.append(bs_)

        # ── Cash Flow ─────────────────────────────────────────────────────
        if page_map.get("cf"):
            rows, from_unit, y1, y2 = extract_table_from_pages(pdf, page_map["cf"])
            log.info(f"[LocalPDF] CF:  {len(rows)} rows, unit={from_unit}, years={y1},{y2}")
            for yr, col in [(y1, 1), (y2, 2)]:
                if yr and (not fiscal_years or yr in fiscal_years):
                    stmt_rows = [{**r, "raw1": r["raw1"] if col == 1 else r["raw2"]} for r in rows]
                    cf_ = map_cash_flow(stmt_rows, from_unit, unit, yr)
                    cash_flows.append(cf_)

    # Build FinancialData
    all_years = sorted(set(
        [s.fiscal_year for s in income_statements] +
        [s.fiscal_year for s in balance_sheets] +
        [s.fiscal_year for s in cash_flows]
    ))

    avg_conf = 0.88
    all_stmts = income_statements + balance_sheets + cash_flows
    if all_stmts:
        avg_conf = sum(s.extraction_confidence for s in all_stmts) / len(all_stmts)

    return FinancialData(
        company_name=company_name,
        currency=currency,
        unit=unit,
        fiscal_years=all_years or fiscal_years,
        income_statements=income_statements,
        balance_sheets=balance_sheets,
        cash_flow_statements=cash_flows,
        metadata=ExtractionMetadata(
            source_type="pdf_local",
            model_used="pdfplumber/local",
            overall_confidence=round(avg_conf, 3),
        ),
    )
