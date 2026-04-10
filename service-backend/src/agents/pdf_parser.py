"""
Local PDF Financial Statement Extractor
========================================
Uses pdfplumber word-position-based extraction — NO API KEY REQUIRED.

Strategy:
  1. Scan every page for financial statement headers (keyword match)
  2. Detect year-column x-boundaries from the "March 31, XXXX" header words
  3. Reconstruct each row: label (left zone) + FY1 value + FY2 value
  4. Map row labels -> financial model fields via regex patterns
  5. Convert units (Millions / Crores / Billions / Thousands)

Handles:
  - Multi-page statements (BS assets + liabilities on separate pages)
  - Bracket negatives:  (10,229.1) -> -10229.1
  - Split-word artefacts: "C ost" -> "Cost"
  - Section headers with no values
  - Notes column (ignored)
  - Both Standalone and Consolidated (prefer Consolidated)
  - International report formats (US, European, Indian)
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import pdfplumber

from models.company_data import ExtractionMetadata, FinancialData
from models.financial_statements import BalanceSheet, CashFlowStatement, IncomeStatement
from utils.logger import get_logger

log = get_logger()

# ---- Types -------------------------------------------------------------------
Row = Dict[str, Optional[float]]
RawTable = List[Dict]


# ---- Number helpers ----------------------------------------------------------

def _parse_number(text: str) -> Optional[float]:
    """
    Parse numbers from PDF text. Handles:
      Indian format: '4,84,968.5' -> 484968.5
      US format: '484,968.5' -> 484968.5
      Bracket negatives: '(10,229.1)' -> -10229.1
      Dashes / Nil -> None
    """
    if not text:
        return None
    text = text.strip()
    if text in ('-', '--', '---', '—', '–', '', 'nil', 'Nil', 'NIL', 'N/A', 'n/a', 'na', 'NA'):
        return None
    negative = text.startswith('(') and text.endswith(')')
    cleaned = re.sub(r'[(),\s₹$€£]', '', text)
    cleaned = cleaned.replace(',', '')
    try:
        val = float(cleaned)
        return -val if negative else val
    except ValueError:
        return None


def _unit_to_crores(value: Optional[float], from_unit: str) -> Optional[float]:
    if value is None:
        return None
    factors = {
        'Crores': 1.0,
        'Millions': 0.1,
        'Billions': 100.0,
        'Thousands': 0.0001,
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


# ---- Page-level helpers ------------------------------------------------------

def _detect_unit(words: List[dict]) -> str:
    header_text = ' '.join(w['text'] for w in words if w['top'] < 180).lower()
    if 'million' in header_text:
        return 'Millions'
    if 'billion' in header_text:
        return 'Billions'
    if 'thousand' in header_text or 'lakh' in header_text:
        return 'Thousands'
    return 'Crores'


def _detect_columns(words: List[dict]) -> Optional[Tuple[float, float, float]]:
    """
    Find (label_max_x, col1_right_x, col2_right_x) from year header words.
    Year words must appear in top 220pt of page.
    Returns None if fewer than 1 year word found.
    """
    year_words = [
        w for w in words
        if re.fullmatch(r'20\d\d', w['text']) and w['top'] < 220
    ]
    if not year_words:
        return None

    year_words.sort(key=lambda w: w['x1'])
    if len(year_words) >= 2:
        col1_right = year_words[-2]['x1']
        col2_right = year_words[-1]['x1']
    else:
        col1_right = year_words[-1]['x1']
        col2_right = col1_right

    label_max = col1_right - 80
    return label_max, col1_right, col2_right


def _extract_years_from_header(words: List[dict]) -> Tuple[Optional[int], Optional[int]]:
    year_words = [
        w for w in words
        if re.fullmatch(r'20\d\d', w['text']) and w['top'] < 220
    ]
    year_words.sort(key=lambda w: w['x1'])
    years = [int(w['text']) for w in year_words]
    y1 = years[-2] if len(years) >= 2 else (years[0] if years else None)
    y2 = years[-1] if len(years) >= 1 else None
    return y1, y2


def _group_rows(words: List[dict], label_max: float,
                col1_right: float, col2_right: float,
                tolerance: float = 3.5) -> List[dict]:
    """
    Group words into rows by vertical position, assign to label / col1 / col2.
    Tolerances are generous to handle slight PDF rendering offsets.
    """
    if not words:
        return []

    words = sorted(words, key=lambda w: (round(w['top'] / tolerance), w['x0']))

    rows: List[dict] = []
    current_top: Optional[float] = None
    current_row: dict = {"label_parts": [], "raw1": None, "raw2": None}

    def flush():
        nonlocal current_row
        if current_row["label_parts"] or current_row["raw1"] or current_row["raw2"]:
            rows.append(current_row)
        current_row = {"label_parts": [], "raw1": None, "raw2": None}

    col_tol = 28  # px tolerance for right-edge alignment

    for w in words:
        top = w['top']
        if current_top is None or abs(top - current_top) > tolerance:
            flush()
            current_top = top
        x0 = w['x0']
        x1 = w['x1']
        if x0 < label_max:
            current_row["label_parts"].append(w['text'])
        elif abs(x1 - col1_right) <= col_tol:
            current_row["raw1"] = w['text']
        elif abs(x1 - col2_right) <= col_tol:
            current_row["raw2"] = w['text']
        # else: notes / reference column — ignore

    flush()

    result = []
    for r in rows:
        label = _clean_label(' '.join(r['label_parts']))
        if not label and not r['raw1'] and not r['raw2']:
            continue
        result.append({"label": label, "raw1": r['raw1'], "raw2": r['raw2']})
    return result


def _clean_label(label: str) -> str:
    label = re.sub(r'(?<!\w)([A-Z]) ([a-z])', r'\1\2', label)
    label = re.sub(r'\s+', ' ', label).strip()
    label = re.sub(r'^\([a-z0-9ivxIVX]+\)\s*', '', label)
    label = re.sub(r'^[ivxIVX]+\.\s*', '', label)
    return label


# ---- Page quality scoring ---------------------------------------------------

def _is_real_statement_page(text: str, words: List[dict]) -> bool:
    """
    Return True only if this page looks like an actual financial statement table,
    not a TOC, footnote, or auditor page that merely mentions statement keywords.

    Criteria:
    - Has at least 1 standalone year word (20XX) in the top 220pt — i.e. the year
      is a column header, not buried inside a long sentence like
      "...for the years ended December 31, 2023, 2022 and 2021"
    - Has at least 10 numeric values (actual table data, not just page numbers)
    - Numeric values spread across at least 2 distinct x-columns
    - The ratio of numeric words to total words is reasonable (>5%) — TOC pages
      have very few numbers relative to their text
    """
    # Year words in header zone that are truly standalone column headers:
    # their surrounding words must NOT be month/date text
    year_words_raw = [w for w in words if re.fullmatch(r'20\d\d', w['text']) and w['top'] < 220]
    if not year_words_raw:
        return False

    # Check that at least one year word is a standalone column header:
    # it should have no adjacent text words within ~30pt horizontally that form a date phrase
    has_standalone_year = False
    for yw in year_words_raw:
        nearby = [w for w in words
                  if w is not yw
                  and abs(w['top'] - yw['top']) < 8
                  and abs(w['x0'] - yw['x1']) < 35]
        nearby_text = ' '.join(w['text'].lower() for w in nearby)
        # If surrounded by date words like "and", "december", "31", it's a sentence
        if not re.search(r'\b(december|january|march|june|and|ended)\b', nearby_text):
            has_standalone_year = True
            break
    if not has_standalone_year:
        return False

    # Must have substantial numeric data (not just page numbers 1-200)
    numeric_words = [
        w for w in words
        if _parse_number(w['text']) is not None
        and abs(_parse_number(w['text'])) > 1.0  # type: ignore[arg-type]
        and w['top'] > 100  # skip header area
    ]
    if len(numeric_words) < 10:
        return False

    # Numeric values must span at least 2 distinct x-columns (columnar table)
    x_buckets = sorted(set(round(w['x1'] / 20) * 20 for w in numeric_words))
    if len(x_buckets) < 2:
        return False

    # Ratio check: TOC/auditor pages have many words but few numbers
    total_words = len([w for w in words if w['top'] > 100])
    if total_words > 0 and len(numeric_words) / total_words < 0.04:
        return False

    return True


# ---- Page scanner -----------------------------------------------------------

# Statement header patterns — anchored/restricted to avoid matching footnotes.
# Key: use word boundaries and require the pattern to be a PAGE TITLE, not
# just a phrase embedded in prose. We enforce this by checking the pattern
# appears in the first 300 characters of the page text (the header area).
_STMT_HEADER_PATTERNS = {
    "pl": [
        r"statement of profit and loss",
        r"profit and loss account",
        r"statement of profit & loss",
        r"profit & loss account",
        r"consolidated statements? of (income|operations|earnings)",
        r"statements? of (income|operations|earnings)",
        r"income statement",
        r"profit and loss statement",
    ],
    "bs": [
        r"balance sheet",
        r"statement of financial position",
        r"consolidated balance sheet",
    ],
    "cf": [
        r"statement of cash flows?",
        r"cash flow statement",
        r"consolidated statements? of cash flows?",
    ],
}

_SCOPE_PATTERNS = {
    "consolidated": [r"consolidated"],
    "standalone":   [r"standalone", r"separate"],
}


def _page_matches_header(page_text: str, patterns: List[str]) -> bool:
    """
    Check if any pattern matches within the FIRST 400 characters of the page
    (the title/header zone). This prevents footnotes from matching.
    """
    header_zone = page_text[:400].lower()
    return any(re.search(p, header_zone) for p in patterns)


def scan_for_statement_pages(pdf, target_years: Optional[List[int]] = None
                             ) -> Dict[str, List[int]]:
    """
    Returns dict: statement_type -> list of 1-based page numbers.
    Prefers consolidated over standalone.
    Only returns pages that pass _is_real_statement_page quality gate.
    """
    results: Dict[str, Dict[str, List[int]]] = {
        "consolidated": {"pl": [], "bs": [], "cf": []},
        "standalone":   {"pl": [], "bs": [], "cf": []},
    }
    page_years: Dict[int, List[int]] = {}

    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        pg_num = i + 1

        # Must have real numbers
        if not re.search(r'\d{3,}', text):
            continue

        words = page.extract_words() or []
        hdr_words = [w for w in words if w['top'] < 220]
        yrs = [int(w['text']) for w in hdr_words if re.fullmatch(r'20\d\d', w['text'])]
        page_years[pg_num] = list(set(yrs))

        # Check statement type — pattern must appear in header zone only
        matched_stmt = None
        for stmt, pats in _STMT_HEADER_PATTERNS.items():
            if _page_matches_header(text, pats):
                matched_stmt = stmt
                break
        if matched_stmt is None:
            continue

        # Quality gate: must look like an actual table, not a footnote
        if not _is_real_statement_page(text, words):
            continue

        # Determine scope; default to standalone
        scope = "standalone"
        for sc, pats in _SCOPE_PATTERNS.items():
            if any(re.search(p, text[:600].lower()) for p in pats):
                scope = sc
                break

        results[scope][matched_stmt].append(pg_num)

    def _filter_by_years(pages: List[int]) -> List[int]:
        if not target_years:
            return pages
        kept = [p for p in pages if any(y in target_years for y in page_years.get(p, []))]
        # If year filtering drops everything, return unfiltered (year may be in body not header)
        return kept if kept else pages

    def _is_continuation_candidate(pg: int, stmt_type: str) -> bool:
        """True if page pg could be a continuation of stmt_type (not a different statement start)."""
        if pg < 1 or pg > len(pdf.pages):
            return False
        pg_text = pdf.pages[pg - 1].extract_text() or ""
        pg_words = pdf.pages[pg - 1].extract_words() or []
        is_other_stmt = any(
            _page_matches_header(pg_text, _STMT_HEADER_PATTERNS[s])
            for s in _STMT_HEADER_PATTERNS if s != stmt_type
        )
        if is_other_stmt:
            return False
        same_header = _page_matches_header(pg_text, _STMT_HEADER_PATTERNS.get(stmt_type, []))
        return same_header or _is_real_statement_page(pg_text, pg_words)

    def _add_continuation(pages: List[int], stmt_type: str) -> List[int]:
        """
        Include adjacent pages (before and after each matched page) that are
        continuations of the same statement. This handles multi-page statements
        where the page scanner only picked up page N but page N-1 or N+1 also
        belongs to the same table.
        """
        expanded = set(pages)
        for p in sorted(pages):
            # Look forward up to 3 pages
            for nxt in range(p + 1, min(p + 4, len(pdf.pages) + 1)):
                if nxt in expanded:
                    continue
                if _is_continuation_candidate(nxt, stmt_type):
                    expanded.add(nxt)
                else:
                    break  # stop at first non-continuation
            # Look backward 1 page (catches case where scanner found page N but N-1 was the real start)
            prev = p - 1
            if prev >= 1 and prev not in expanded and _is_continuation_candidate(prev, stmt_type):
                expanded.add(prev)
        return sorted(expanded)

    final: Dict[str, List[int]] = {}
    for stmt in ("pl", "bs", "cf"):
        pages = results["consolidated"][stmt] or results["standalone"][stmt]
        if not pages:
            continue
        pages = _filter_by_years(pages)
        pages = _add_continuation(pages, stmt)
        final[stmt] = pages[:5]  # up to 5 pages per statement

    return final


# ---- Multi-page table extractor ---------------------------------------------

def extract_table_from_pages(pdf, page_nums: List[int]) -> Tuple[RawTable, str, int, int]:
    """
    Extract rows from one or more pages of the same statement.
    Returns (rows, detected_unit, year1, year2).
    """
    all_rows: RawTable = []
    detected_unit = "Crores"
    year1: Optional[int] = None
    year2: Optional[int] = None
    label_max: float = 0
    col1_right: float = 0
    col2_right: float = 0

    for pg_num in page_nums:
        page = pdf.pages[pg_num - 1]
        words = page.extract_words(keep_blank_chars=False, x_tolerance=2, y_tolerance=3)
        if not words:
            continue

        col_info = _detect_columns(words)
        if col_info is not None:
            new_label_max, new_col1, new_col2 = col_info
            if year1 is None:
                detected_unit = _detect_unit(words)
                label_max, col1_right, col2_right = new_label_max, new_col1, new_col2
                y1, y2 = _extract_years_from_header(words)
                year1 = y1
                year2 = y2
            else:
                # Continuation: update columns but keep unit from page 1
                label_max, col1_right, col2_right = new_label_max, new_col1, new_col2
        elif year1 is None:
            log.warning(f"[LocalPDF] Could not detect columns on page {pg_num} — skipping")
            continue

        # Skip header area on continuation pages
        data_words = [w for w in words if w['top'] > 165] if all_rows else words
        rows = _group_rows(data_words, label_max, col1_right, col2_right)
        all_rows.extend(rows)

    return all_rows, detected_unit, year1 or 0, year2 or 0


# ---- Field pattern helpers --------------------------------------------------

def _norm(label: str) -> str:
    return re.sub(r'[^a-z0-9 ]', ' ', label.lower())


def _match(label: str, patterns: List[str]) -> bool:
    n = _norm(label)
    return any(re.search(p, n) for p in patterns)


def _first(rows: RawTable, patterns: List[str],
           from_unit: str, to_unit: str) -> Optional[float]:
    for r in rows:
        if r['label'] and _match(r['label'], patterns):
            val = _convert(_parse_number(r['raw1']), from_unit, to_unit)
            if val is not None:
                return val
    return None


def _first2(rows: RawTable, patterns: List[str],
            from_unit: str, to_unit: str) -> Tuple[Optional[float], Optional[float]]:
    for r in rows:
        if r['label'] and _match(r['label'], patterns):
            v1 = _convert(_parse_number(r['raw1']), from_unit, to_unit)
            v2 = _convert(_parse_number(r['raw2']), from_unit, to_unit)
            return v1, v2
    return None, None


# ---- Income Statement mapper ------------------------------------------------

_IS_FIELDS: Dict[str, List[str]] = {
    "revenue": [
        # Indian formats
        r"revenue from operations",
        r"net sales",
        r"net revenue",
        r"total revenue",
        r"total net revenue",
        r"revenues",
        r"^revenue$",
        r"turnover",
        r"net turnover",
        r"gross revenue",
        r"sales revenue",
        r"income from operations",
        r"total income from operations",
        r"total net sales",
        r"net sales and revenues",
        # US / international formats
        r"^sales$",
        r"total sales",
        r"product sales",
        r"service revenue",
        r"total revenues",
    ],
    "other_income": [
        r"other income",
        r"other operating income",
        r"other revenue",
        r"non.operating income",
    ],
    "cost_of_goods_sold": [
        # IT/service company cost of revenue first (avoid matching tiny incidental costs)
        r"cost of revenue",
        r"cost of services",
        r"subcontracting",
        # Manufacturing / FMCG formats
        r"cost of materials consumed",
        r"cost of goods sold",
        r"cost of sales",
        r"cost of products sold",
        r"raw material",
        r"cost of material",
        r"direct cost",
    ],
    "purchases_trading": [
        r"purchases of stock.in.trade",
        r"purchases of traded goods",
        r"purchase of stock",
        r"trading purchases",
    ],
    "changes_in_inventory": [
        r"changes in inventor",
        r"change in stock",
        r"increase.decrease in inventor",
        r"(increase) decrease in inventor",
    ],
    "employee_expenses": [
        r"employee benefit",
        r"employee cost",
        r"staff cost",
        r"remuneration",
        r"personnel expense",
        r"salaries and wages",
        r"compensation and benefits",
        r"labor and related",
    ],
    "finance_costs": [
        r"finance cost",
        r"finance charges",
        r"interest expense",
        r"financial cost",
        r"interest and bank charges",
        r"net interest expense",
    ],
    "depreciation_amortization": [
        r"depreciation and amortis",
        r"depreciation and amortiz",
        r"depreciation.*amortization",
        r"depreciation depletion",
        r"amortization and depreciation",
        r"depreciation.*depletion.*amortiz",
        r"^depreciation$",
    ],
    "other_expenses": [
        r"other expense",
        r"other operating expense",
        r"general.*administrative",
        r"selling.*general.*administrative",
        r"selling.*marketing",
        r"distribution expense",
        r"administrative expense",
    ],
    "total_expenses": [
        r"total expense",
        r"total operating expense",
        r"total costs and expense",
    ],
    "gross_profit": [
        r"gross profit",
        r"gross margin",
        r"gross income",
    ],
    "ebitda": [
        r"\bebitda\b",
        r"earnings before interest.*tax.*depreciation",
    ],
    "profit_before_tax": [
        r"profit before tax",
        r"earnings before tax",
        r"income before.*tax",
        r"profit before income tax",
        r"\bpbt\b",
        r"\bebt\b",
        r"income before provision",
    ],
    "tax_expense": [
        r"tax expense",
        r"income tax expense",
        r"provision for.*tax",
        r"income tax provision",
        r"total tax",
        r"total income tax",
    ],
    "current_tax":  [r"current tax"],
    "deferred_tax": [r"deferred tax"],
    "pat": [
        # NOTE: "total comprehensive income" is intentionally excluded.
        # Under Ind AS / IFRS, TCI = PAT + OCI (FX, actuarial gains, etc.)
        # Using TCI overstates earnings by 6-11% (the OCI amount).
        r"profit for the year",
        r"profit after tax",
        r"net profit",
        r"profit for period",
        r"net income",
        r"net earnings",
        r"profit attributable",
        r"net income attributable",
    ],
    "eps_basic": [
        r"basic.*earnings per share",
        r"basic.*eps",
        r"earnings per share.*basic",
    ],
    "eps_diluted": [
        r"diluted.*earnings per share",
        r"diluted.*eps",
        r"earnings per share.*diluted",
    ],
}


def map_income_statement(rows: RawTable, from_unit: str, to_unit: str,
                         fiscal_year: int) -> IncomeStatement:
    g = lambda *pats: _first(rows, list(pats), from_unit, to_unit)

    labels = [r['label'] for r in rows if r['label']]
    log.info(f"[LocalPDF] P&L row labels (fy={fiscal_year}): {labels}")

    revenue      = g(*_IS_FIELDS["revenue"])
    other_income = g(*_IS_FIELDS["other_income"])
    cogs         = g(*_IS_FIELDS["cost_of_goods_sold"])
    purchases    = g(*_IS_FIELDS["purchases_trading"])
    inv_chg      = g(*_IS_FIELDS["changes_in_inventory"])
    employee     = g(*_IS_FIELDS["employee_expenses"])
    finance      = g(*_IS_FIELDS["finance_costs"])
    depn         = g(*_IS_FIELDS["depreciation_amortization"])
    other_exp    = g(*_IS_FIELDS["other_expenses"])
    total_exp    = g(*_IS_FIELDS["total_expenses"])
    gross_profit = g(*_IS_FIELDS["gross_profit"])
    pbt          = g(*_IS_FIELDS["profit_before_tax"])
    tax          = g(*_IS_FIELDS["tax_expense"])
    pat          = g(*_IS_FIELDS["pat"])
    eps_basic    = g(*_IS_FIELDS["eps_basic"])
    eps_diluted  = g(*_IS_FIELDS["eps_diluted"])

    # Derived: revenue from gross profit + COGS when revenue line is missing
    # (common in US reports where the revenue row is on a prior page)
    if revenue is None and gross_profit is not None and cogs is not None:
        revenue = gross_profit + abs(cogs)
        log.info(f"[LocalPDF] Revenue derived from GrossProfit+COGS: {revenue}")

    # Derived: gross profit if not directly available
    if gross_profit is None and revenue is not None:
        deductions = sum(x for x in [cogs, purchases, inv_chg] if x is not None)
        if deductions:
            gross_profit = revenue - deductions

    # Derived: EBITDA bottom-up
    ebitda: Optional[float] = None
    if pbt is not None:
        add_backs = sum(x for x in [finance, depn] if x is not None)
        if add_backs:
            ebitda = pbt + add_backs

    # Derived: EBIT
    ebit: Optional[float] = None
    if ebitda is not None and depn is not None:
        ebit = ebitda - depn

    # Confidence: penalise if key fields missing
    conf = 0.92
    if revenue is None:
        conf -= 0.25
    if pat is None:
        conf -= 0.10
    if pbt is None:
        conf -= 0.05

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
        eps_basic=eps_basic,
        eps_diluted=eps_diluted,
        extraction_confidence=round(conf, 3),
    )


# ---- Balance Sheet mapper ---------------------------------------------------

def map_balance_sheet(rows: RawTable, from_unit: str, to_unit: str,
                      fiscal_year: int) -> BalanceSheet:
    """Section-aware BS mapper. Tracks current section to disambiguate borrowings."""

    section = "unknown"
    vals_by_section: Dict[str, Dict[str, Optional[float]]] = {
        "assets": {}, "nc_liab": {}, "curr_liab": {}, "equity": {}, "unknown": {}
    }
    vals_flat: Dict[str, Optional[float]] = {}

    for r in rows:
        lbl = r['label']
        if not lbl:
            continue
        n = _norm(lbl)
        v = _convert(_parse_number(r['raw1']), from_unit, to_unit)

        # Update section
        if re.search(r'\b(total )?assets\b', n) and not re.search(r'liabilit', n):
            section = "assets"
        elif re.search(r'non.current liabilit', n):
            section = "nc_liab"
        elif re.search(r'current liabilit', n) and 'non' not in n:
            section = "curr_liab"
        elif re.search(r'\bequity\b', n) and not re.search(r'liabilit', n):
            section = "equity"

        vals_by_section[section][n] = v
        vals_flat[n] = v

    def g(*patterns: str) -> Optional[float]:
        for pat in patterns:
            for key, val in vals_flat.items():
                if re.search(pat, key) and val is not None:
                    return val
        return None

    def g_sec(sec: str, *patterns: str) -> Optional[float]:
        for pat in patterns:
            for key, val in vals_by_section.get(sec, {}).items():
                if re.search(pat, key) and val is not None:
                    return val
        return None

    # Assets
    ppe             = g(r"property.*plant.*equipment", r"property and equipment",
                        r"tangible asset", r"fixed asset", r"net property")
    cwip            = g(r"capital work.in.progress", r"cwip", r"construction in progress")
    goodwill        = g(r"\bgoodwill\b")
    intangibles     = g(r"other intangible", r"intangible asset", r"intangibles, net")
    rou             = g(r"right.of.use", r"rou asset", r"operating lease.*right")
    nc_invest       = g(r"non.current.*investment", r"long.term investment",
                        r"financial asset.*investment")
    dta             = g(r"deferred tax asset")
    other_nc_assets = g(r"other non.current asset", r"other long.term asset")
    total_nc_assets = g(r"total non.current asset", r"total long.term asset")
    inventories     = g(r"\binventor", r"\bstock\b")
    receivables     = g(r"trade receivable", r"accounts receivable", r"debtor",
                        r"receivables, net")
    cash            = g(r"cash and cash equivalent", r"cash and short.term investment",
                        r"cash, cash equivalent")
    bank_bal        = g(r"other bank balance", r"bank balance other")
    curr_invest     = g(r"current investment", r"short.term investment",
                        r"marketable securities", r"short.term marketable")
    other_curr_ass  = g(r"other current asset", r"prepaid.*other")
    total_curr_ass  = g(r"total current asset")
    total_assets    = g(r"total asset")

    # Equity
    share_capital   = g(r"equity share capital", r"share capital", r"common stock",
                        r"ordinary shares", r"paid.in capital")
    other_equity    = g(r"other equity", r"reserves and surplus", r"retained earnings",
                        r"accumulated.*deficit", r"additional paid.in",
                        r"shareholder.*equity", r"stockholder.*equity")
    nci             = g(r"non.controlling interest", r"minority interest")
    total_equity    = g(r"total equity", r"total stockholder", r"total shareholder",
                        r"total owners.*equity")

    # Liabilities (section-aware to disambiguate borrowings)
    lt_borrow    = g_sec("nc_liab", r"\bborrowing", r"long.term debt", r"long.term loan",
                         r"notes payable", r"debenture", r"bonds payable")
    st_borrow    = g_sec("curr_liab", r"\bborrowing", r"short.term debt",
                         r"current.*long.term debt", r"current portion.*debt",
                         r"short.term loan", r"commercial paper")
    lease_nc     = g_sec("nc_liab", r"lease liabilit", r"finance lease")
    lease_curr   = g_sec("curr_liab", r"lease liabilit")
    dt_liab      = g(r"deferred tax liabilit")
    other_nc_liab = g(r"other non.current liabilit", r"other long.term liabilit")
    total_nc_liab = g(r"total non.current liabilit", r"total long.term liabilit")
    trade_pay    = g(r"trade payable", r"accounts payable", r"creditor")
    other_cl     = g(r"other current liabilit", r"accrued.*liabilit",
                     r"accrued expense", r"accrued and other")
    total_cl     = g(r"total current liabilit")

    # Combine traditional borrowings with Ind AS 116 / IFRS 16 lease liabilities.
    # For asset-light companies (IT, FMCG) lease liabilities ARE the primary debt.
    lt_debt_total: Optional[float] = None
    if lt_borrow is not None or lease_nc is not None:
        lt_debt_total = (lt_borrow or 0) + (lease_nc or 0)

    st_debt_total: Optional[float] = None
    if st_borrow is not None or lease_curr is not None:
        st_debt_total = (st_borrow or 0) + (lease_curr or 0)

    # Net debt computation
    total_debt: Optional[float] = None
    if lt_debt_total is not None or st_debt_total is not None:
        total_debt = (lt_debt_total or 0) + (st_debt_total or 0)

    net_debt: Optional[float] = None
    if total_debt is not None and cash is not None:
        net_debt = total_debt - cash - (bank_bal or 0) - (curr_invest or 0)

    # Confidence: penalise for missing totals
    conf = 0.92
    if total_assets is None:
        conf -= 0.10
    if total_equity is None:
        conf -= 0.05

    return BalanceSheet(
        fiscal_year=fiscal_year,
        net_fixed_assets=ppe,
        capital_wip=cwip,
        goodwill=goodwill,
        intangible_assets=intangibles,
        long_term_investments=nc_invest,
        deferred_tax_assets=dta,
        other_non_current_assets=other_nc_assets,
        total_non_current_assets=total_nc_assets,
        inventory=inventories,
        accounts_receivable=receivables,
        cash_and_equivalents=cash,
        short_term_investments=curr_invest or bank_bal,
        other_current_assets=other_curr_ass,
        total_current_assets=total_curr_ass,
        total_assets=total_assets,
        share_capital=share_capital,
        reserves_and_surplus=other_equity,
        minority_interest=nci,
        total_equity=total_equity,
        # Non-current liabilities (borrowings + Ind AS 116 lease liabilities combined)
        long_term_debt=lt_debt_total,
        deferred_tax_liabilities=dt_liab,
        other_non_current_liabilities=other_nc_liab,
        total_non_current_liabilities=total_nc_liab,
        # Current liabilities (borrowings + current lease liabilities combined)
        short_term_borrowings=st_debt_total,
        accounts_payable=trade_pay,
        other_current_liabilities=other_cl,
        total_current_liabilities=total_cl,
        total_liabilities_and_equity=total_assets,
        extraction_confidence=round(conf, 3),
    )


# ---- Cash Flow mapper -------------------------------------------------------

def map_cash_flow(rows: RawTable, from_unit: str, to_unit: str,
                  fiscal_year: int) -> CashFlowStatement:
    g = lambda *pats: _first(rows, list(pats), from_unit, to_unit)

    pbt         = g(r"profit before tax", r"income before.*tax", r"net income before tax")
    depn        = g(r"depreciation and amortis", r"depreciation and amortiz",
                    r"depreciation.*amortization", r"^depreciation$",
                    r"depreciation depletion")
    cfo         = g(r"net cash.*from operating", r"net cash generated from operating",
                    r"net cash.*operating activit", r"net cash provided by operating",
                    r"cash flow from operation", r"net cash from operation")
    capex       = g(r"purchase of property", r"additions to.*property",
                    r"capital expenditure", r"purchase.*ppe",
                    r"acquisition.*property plant",
                    r"capital expenditures",
                    r"purchases of property",
                    r"purchase.*equipment",
                    r"property.*plant.*equipment.*purchased")
    asset_sale  = g(r"proceeds.*sale.*property", r"proceeds from disposal",
                    r"sale of property", r"proceeds.*property.*plant")
    buy_invest  = g(r"purchase.*investment", r"acquisition.*investment",
                    r"purchase.*marketable securities")
    sell_invest = g(r"proceeds.*sale.*investment", r"proceeds.*investment",
                    r"maturities.*marketable securities")
    div_recv    = g(r"dividend received")
    int_recv    = g(r"interest received", r"interest income received")
    cfi         = g(r"net cash.*from investing", r"net cash used in investing",
                    r"net cash.*investing activit", r"net cash provided by investing",
                    r"cash flow from investing")
    proc_borrow = g(r"proceeds from borrowing", r"proceeds from.*debt",
                    r"proceeds from.*loan", r"proceeds from issuance.*debt")
    repay_borrow = g(r"repayment of borrowing", r"repayment.*loan",
                     r"repayment.*debt", r"payment.*long.term debt")
    div_paid    = g(r"dividend paid", r"dividends paid", r"payment.*dividend")
    int_paid    = g(r"interest paid", r"finance cost paid")
    buyback     = g(r"repurchase.*share", r"buyback", r"share repurchase",
                    r"repurchase of common")
    cff         = g(r"net cash.*from financing", r"net cash used in financing",
                    r"net cash.*financing activit", r"net cash provided by financing",
                    r"cash flow from financing")
    open_cash   = g(r"cash.*beginning", r"opening.*cash", r"cash.*at.*beginning",
                    r"cash.*start of")
    close_cash  = g(r"cash.*end", r"closing.*cash", r"cash.*at.*end",
                    r"cash.*end of year", r"cash.*end of period")

    fcf: Optional[float] = None
    if cfo is not None and capex is not None:
        fcf = cfo + capex

    net_change: Optional[float] = None
    if open_cash is not None and close_cash is not None:
        net_change = close_cash - open_cash

    conf = 0.90
    if cfo is None:
        conf -= 0.15
    if capex is None:
        conf -= 0.05

    return CashFlowStatement(
        fiscal_year=fiscal_year,
        net_income=pbt,
        depreciation_amortization=depn,
        cash_from_operations=cfo,
        capex=capex,
        proceeds_from_asset_sales=asset_sale,
        cash_from_investing=cfi,
        debt_raised=proc_borrow,
        debt_repaid=repay_borrow,
        dividends_paid=div_paid,
        share_buyback=buyback,
        cash_from_financing=cff,
        net_change_in_cash=net_change,
        opening_cash=open_cash,
        closing_cash=close_cash,
        free_cash_flow=fcf,
        extraction_confidence=round(conf, 3),
    )


# ---- Year-column helper -----------------------------------------------------

def _year_cols_for_stmt(y1: int, y2: int, supplied: List[int]) -> List[Tuple[int, int]]:
    """
    Decide which (fiscal_year, col) pairs to extract.
    - If y1 != y2: use both columns filtered to supplied years.
    - If y1 == y2 (duplicate header): use col=1 with the latest supplied year.
    - Fallback: if nothing matched but we have rows, use col=1 with latest supplied.
    """
    pairs: List[Tuple[int, int]] = []
    if y1 and y2 and y1 != y2:
        for yr, col in [(y1, 1), (y2, 2)]:
            if not supplied or yr in supplied:
                pairs.append((yr, col))
    elif y1 and (not supplied or y1 in supplied):
        pairs.append((y1, 1))

    if not pairs and supplied and (y1 or y2):
        # Fallback: use latest supplied year with col 1
        pairs.append((supplied[-1], 1))

    return pairs


# ---- Public API -------------------------------------------------------------

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

        # ---- Income Statement
        if page_map.get("pl"):
            rows, from_unit, y1, y2 = extract_table_from_pages(pdf, page_map["pl"])
            log.info(f"[LocalPDF] P&L: {len(rows)} rows, unit={from_unit}, years={y1},{y2}")
            for yr, col in _year_cols_for_stmt(y1, y2, fiscal_years):
                stmt_rows = [{**r, "raw1": r["raw1"] if col == 1 else r["raw2"]} for r in rows]
                income_statements.append(map_income_statement(stmt_rows, from_unit, unit, yr))

        # ---- Balance Sheet
        if page_map.get("bs"):
            rows, from_unit, y1, y2 = extract_table_from_pages(pdf, page_map["bs"])
            log.info(f"[LocalPDF] BS:  {len(rows)} rows, unit={from_unit}, years={y1},{y2}")
            for yr, col in _year_cols_for_stmt(y1, y2, fiscal_years):
                stmt_rows = [{**r, "raw1": r["raw1"] if col == 1 else r["raw2"]} for r in rows]
                balance_sheets.append(map_balance_sheet(stmt_rows, from_unit, unit, yr))

        # ---- Cash Flow
        if page_map.get("cf"):
            rows, from_unit, y1, y2 = extract_table_from_pages(pdf, page_map["cf"])
            log.info(f"[LocalPDF] CF:  {len(rows)} rows, unit={from_unit}, years={y1},{y2}")
            for yr, col in _year_cols_for_stmt(y1, y2, fiscal_years):
                stmt_rows = [{**r, "raw1": r["raw1"] if col == 1 else r["raw2"]} for r in rows]
                cash_flows.append(map_cash_flow(stmt_rows, from_unit, unit, yr))

    all_years = sorted(set(
        [s.fiscal_year for s in income_statements] +
        [s.fiscal_year for s in balance_sheets] +
        [s.fiscal_year for s in cash_flows]
    ))

    all_stmts = income_statements + balance_sheets + cash_flows
    avg_conf = (sum(s.extraction_confidence for s in all_stmts) / len(all_stmts)
                if all_stmts else 0.5)

    # If P&L pages were found but revenue is still None, lower confidence
    # so extractor.py triggers the Claude API gap-fill pass.
    has_revenue = any(s.revenue is not None and s.revenue > 0 for s in income_statements)
    if page_map.get("pl") and not has_revenue:
        log.warning("[LocalPDF] P&L pages found but no revenue mapped — lowering confidence to trigger API gap-fill.")
        avg_conf = min(avg_conf, 0.50)

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
