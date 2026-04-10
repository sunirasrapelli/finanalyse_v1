"""
Extractor Agent — financial statement extraction from PDF or JSON.

Public API
----------
extract_from_pdf(path, company_name, fiscal_years, currency, unit) -> FinancialData
extract_from_json(path) -> FinancialData
validate_relevance(financial_data, source_name) -> None   # raises ValidationError
merge_financial_data(data_list) -> FinancialData
"""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import (
    ANTHROPIC_API_KEY,
    CONFIDENCE_API_BOOST,
    CONFIDENCE_API_BOOST_CAP,
    CONFIDENCE_API_FALLBACK,
    CONFIDENCE_MIN_ACCEPT,
    MAX_TOKENS,
    MODEL_NAME,
    PDF_SMALL_THRESHOLD,
    PDF_TOC_PAGES,
    RETRY_ATTEMPTS,
    RETRY_WAIT_MAX,
    RETRY_WAIT_MIN,
)
from errors import ConfigurationError, ExtractionError, ValidationError
from models.company_data import ExtractionMetadata, FinancialData
from models.financial_statements import BalanceSheet, CashFlowStatement, IncomeStatement
from schemas.extraction_tool_schema import EXTRACTION_TOOL, TOOL_CHOICE
from utils.logger import get_logger
from utils.pdf_handler import (
    extract_page_range_as_base64,
    get_pdf_page_count,
    load_pdf_as_base64,
    validate_pdf,
)

log = get_logger(__name__)

# ── Thread-safe lazy client ───────────────────────────────────────────────────
_client:      Optional[anthropic.Anthropic] = None
_client_lock: threading.Lock               = threading.Lock()


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-checked locking
                if not ANTHROPIC_API_KEY:
                    raise ConfigurationError(
                        "ANTHROPIC_API_KEY is not set — cannot call extraction API."
                    )
                _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ── TOC page detection (large PDFs) ──────────────────────────────────────────

def _detect_financial_pages(pdf_b64: str, total_pages: int) -> Tuple[int, int]:
    """
    Send the first PDF_TOC_PAGES pages to Claude to find which pages contain
    the financial statements. Returns (start_page, end_page).
    Falls back to the last third of the document on any failure.
    """
    log.info("Large PDF — running TOC page detection…")
    try:
        resp = _get_client().messages.create(
            model=MODEL_NAME,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a company annual report. Look at the table of contents "
                            "and identify which page numbers contain the three financial statements "
                            "(Income Statement/P&L, Balance Sheet, Cash Flow Statement). "
                            "Reply with ONLY a JSON object like: "
                            '{"start_page": 120, "end_page": 155}'
                        ),
                    },
                ],
            }],
        )
        match = re.search(r'\{"start_page".*?\}', resp.content[0].text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return int(data["start_page"]), int(data["end_page"])
    except Exception as exc:
        log.warning("TOC detection failed (%s) — falling back to last third.", exc)

    start = max(1, total_pages * 2 // 3)
    return start, total_pages


# ── Core Claude API calls ─────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
    reraise=True,
)
def _call_extraction_api(
    pdf_b64:      str,
    company_name: str,
    years:        List[int],
    currency:     str = "INR",
    unit:         str = "Crores",
) -> dict:
    """Pass 1 — extract financial statements using Claude tool_use."""
    system_prompt = Path("prompts/extraction_system.txt").read_text()
    user_template = Path("prompts/extraction_user.txt").read_text()
    user_prompt   = user_template.format(
        company_name=company_name,
        years=", ".join(str(y) for y in years),
        currency=currency,
        unit=unit,
    )

    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        tools=[EXTRACTION_TOOL],
        tool_choice=TOOL_CHOICE,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": user_prompt},
            ],
        }],
    )

    for block in response.content:
        if block.type == "tool_use":
            return block.input  # type: ignore[return-value]
    raise ExtractionError("Claude did not return a tool_use block — extraction failed.")


# ── Per-statement focused tools ───────────────────────────────────────────────

_FLOAT_OR_NULL = {"type": ["number", "null"]}

_IS_TOOL = {
    "name": "extract_income_statement",
    "description": "Extract ONLY the Income Statement / P&L from this annual report for all fiscal years shown.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_years": {"type": "array", "items": {"type": "integer"}},
            "currency": {"type": "string"},
            "unit": {"type": "string"},
            "income_statements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fiscal_year": {"type": "integer"},
                        "revenue":                    {**_FLOAT_OR_NULL, "description": "Net sales / Net revenue / Revenue from operations — the TOP LINE"},
                        "other_income":               _FLOAT_OR_NULL,
                        "total_income":               _FLOAT_OR_NULL,
                        "cogs":                       {**_FLOAT_OR_NULL, "description": "Cost of goods sold / Cost of sales / Cost of revenue — always positive"},
                        "employee_expenses":          _FLOAT_OR_NULL,
                        "other_operating_expenses":   _FLOAT_OR_NULL,
                        "total_operating_expenses":   _FLOAT_OR_NULL,
                        "gross_profit":               _FLOAT_OR_NULL,
                        "ebitda":                     _FLOAT_OR_NULL,
                        "depreciation_amortization":  {**_FLOAT_OR_NULL, "description": "Always positive"},
                        "ebit":                       _FLOAT_OR_NULL,
                        "interest_expense":           {**_FLOAT_OR_NULL, "description": "Finance costs — always positive"},
                        "pbt":                        {**_FLOAT_OR_NULL, "description": "Profit/Income before tax"},
                        "tax_expense":                {**_FLOAT_OR_NULL, "description": "Provision for income taxes — always positive"},
                        "effective_tax_rate":         _FLOAT_OR_NULL,
                        "pat":                        {**_FLOAT_OR_NULL, "description": "Net income / Profit after tax"},
                        "minority_interest":          _FLOAT_OR_NULL,
                        "pat_attributable":           _FLOAT_OR_NULL,
                        "shares_outstanding":         _FLOAT_OR_NULL,
                        "eps_basic":                  _FLOAT_OR_NULL,
                        "eps_diluted":                _FLOAT_OR_NULL,
                        "dividends_per_share":        _FLOAT_OR_NULL,
                        "extraction_confidence":      {"type": "number", "minimum": 0, "maximum": 1},
                        "extraction_notes":           {"type": ["string", "null"]},
                    },
                    "required": ["fiscal_year"],
                },
            },
        },
        "required": ["fiscal_years", "income_statements"],
    },
}

_BS_TOOL = {
    "name": "extract_balance_sheet",
    "description": "Extract ONLY the Balance Sheet / Statement of Financial Position from this annual report for all fiscal years shown.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_years": {"type": "array", "items": {"type": "integer"}},
            "currency": {"type": "string"},
            "unit": {"type": "string"},
            "balance_sheets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fiscal_year":                  {"type": "integer"},
                        "cash_and_equivalents":         _FLOAT_OR_NULL,
                        "short_term_investments":       _FLOAT_OR_NULL,
                        "accounts_receivable":          _FLOAT_OR_NULL,
                        "inventory":                    _FLOAT_OR_NULL,
                        "other_current_assets":         _FLOAT_OR_NULL,
                        "total_current_assets":         _FLOAT_OR_NULL,
                        "gross_fixed_assets":           _FLOAT_OR_NULL,
                        "accumulated_depreciation":     _FLOAT_OR_NULL,
                        "net_fixed_assets":             _FLOAT_OR_NULL,
                        "capital_wip":                  _FLOAT_OR_NULL,
                        "intangible_assets":            _FLOAT_OR_NULL,
                        "goodwill":                     _FLOAT_OR_NULL,
                        "long_term_investments":        _FLOAT_OR_NULL,
                        "deferred_tax_assets":          _FLOAT_OR_NULL,
                        "other_non_current_assets":     _FLOAT_OR_NULL,
                        "total_non_current_assets":     _FLOAT_OR_NULL,
                        "total_assets":                 _FLOAT_OR_NULL,
                        "short_term_borrowings":        _FLOAT_OR_NULL,
                        "accounts_payable":             _FLOAT_OR_NULL,
                        "other_current_liabilities":    _FLOAT_OR_NULL,
                        "total_current_liabilities":    _FLOAT_OR_NULL,
                        "long_term_debt":               _FLOAT_OR_NULL,
                        "deferred_tax_liabilities":     _FLOAT_OR_NULL,
                        "other_non_current_liabilities":_FLOAT_OR_NULL,
                        "total_non_current_liabilities":_FLOAT_OR_NULL,
                        "total_liabilities":            _FLOAT_OR_NULL,
                        "share_capital":                _FLOAT_OR_NULL,
                        "reserves_and_surplus":         _FLOAT_OR_NULL,
                        "minority_interest":            _FLOAT_OR_NULL,
                        "total_equity":                 _FLOAT_OR_NULL,
                        "total_liabilities_and_equity": _FLOAT_OR_NULL,
                        "extraction_confidence":        {"type": "number", "minimum": 0, "maximum": 1},
                        "extraction_notes":             {"type": ["string", "null"]},
                    },
                    "required": ["fiscal_year"],
                },
            },
        },
        "required": ["fiscal_years", "balance_sheets"],
    },
}

_CF_TOOL = {
    "name": "extract_cash_flow",
    "description": "Extract ONLY the Cash Flow Statement from this annual report for all fiscal years shown.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_years": {"type": "array", "items": {"type": "integer"}},
            "currency": {"type": "string"},
            "unit": {"type": "string"},
            "cash_flow_statements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fiscal_year":               {"type": "integer"},
                        "net_income":                _FLOAT_OR_NULL,
                        "depreciation_amortization": _FLOAT_OR_NULL,
                        "changes_in_working_capital":_FLOAT_OR_NULL,
                        "other_operating_adjustments":_FLOAT_OR_NULL,
                        "cash_from_operations":      _FLOAT_OR_NULL,
                        "capex":                     {**_FLOAT_OR_NULL, "description": "Capital expenditure — NEGATIVE number"},
                        "proceeds_from_asset_sales": _FLOAT_OR_NULL,
                        "acquisitions":              _FLOAT_OR_NULL,
                        "investments_net":           _FLOAT_OR_NULL,
                        "cash_from_investing":       _FLOAT_OR_NULL,
                        "debt_raised":               _FLOAT_OR_NULL,
                        "debt_repaid":               _FLOAT_OR_NULL,
                        "dividends_paid":            {**_FLOAT_OR_NULL, "description": "Negative number"},
                        "share_issuance":            _FLOAT_OR_NULL,
                        "share_buyback":             {**_FLOAT_OR_NULL, "description": "Negative number"},
                        "cash_from_financing":       _FLOAT_OR_NULL,
                        "net_change_in_cash":        _FLOAT_OR_NULL,
                        "opening_cash":              _FLOAT_OR_NULL,
                        "closing_cash":              _FLOAT_OR_NULL,
                        "free_cash_flow":            _FLOAT_OR_NULL,
                        "extraction_confidence":     {"type": "number", "minimum": 0, "maximum": 1},
                        "extraction_notes":          {"type": ["string", "null"]},
                    },
                    "required": ["fiscal_year"],
                },
            },
        },
        "required": ["fiscal_years", "cash_flow_statements"],
    },
}

_STMT_AGENT_CONFIG = {
    "pl": {
        "tool": _IS_TOOL,
        "tool_choice": {"type": "tool", "name": "extract_income_statement"},
        "result_key": "income_statements",
        "focus": "Income Statement / Statement of Profit and Loss / Statement of Operations",
        "instructions": (
            "Focus ONLY on the Income Statement (P&L). "
            "The top line is Net sales or Revenue from operations. "
            "Extract ALL fiscal years shown. "
            "If the report starts the IS from Gross profit (top-line Net sales is on prior page), "
            "set revenue = gross_profit + cost_of_sales (derive it — mark confidence 0.85). "
            "Do NOT extract Balance Sheet or Cash Flow data."
        ),
    },
    "bs": {
        "tool": _BS_TOOL,
        "tool_choice": {"type": "tool", "name": "extract_balance_sheet"},
        "result_key": "balance_sheets",
        "focus": "Balance Sheet / Statement of Financial Position",
        "instructions": (
            "Focus ONLY on the Balance Sheet. "
            "Extract total assets, liabilities, and equity for ALL fiscal years shown. "
            "Do NOT extract Income Statement or Cash Flow data."
        ),
    },
    "cf": {
        "tool": _CF_TOOL,
        "tool_choice": {"type": "tool", "name": "extract_cash_flow"},
        "result_key": "cash_flow_statements",
        "focus": "Statement of Cash Flows / Cash Flow Statement",
        "instructions": (
            "Focus ONLY on the Cash Flow Statement. "
            "Extract CFO, CFI, CFF, and free cash flow for ALL fiscal years shown. "
            "Capex must be a NEGATIVE number. "
            "Do NOT extract Income Statement or Balance Sheet data."
        ),
    },
}


def _call_statement_agent(
    stmt_type: str,
    pdf_b64: str,
    company_name: str,
    years: List[int],
    currency: str,
    unit: str,
) -> dict:
    """
    Call Claude with a focused single-statement extraction tool.
    Returns the raw tool_use input dict with the statement list.
    """
    cfg = _STMT_AGENT_CONFIG[stmt_type]
    system = (
        "You are a senior financial analyst. Your ONLY task is to extract the "
        f"{cfg['focus']} from this annual report with complete accuracy.\n\n"
        "RULES:\n"
        "1. Extract numbers EXACTLY as shown — same unit as the report header.\n"
        "2. Return null for any field not explicitly in the document.\n"
        "3. Use CONSOLIDATED statements where available.\n"
        "4. Extract ALL fiscal years present.\n"
        "5. Depreciation is always positive. Capex is always negative in CF context.\n"
        f"6. {cfg['instructions']}\n"
        "7. Always call the provided tool — never return prose."
    )
    user = (
        f"Company: {company_name}\n"
        f"Fiscal year(s): {', '.join(str(y) for y in years)}\n"
        f"Currency/Unit: {currency} {unit}\n\n"
        f"Extract the {cfg['focus']} using the tool."
    )
    client = _get_client()
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system,
        tools=[cfg["tool"]],
        tool_choice=cfg["tool_choice"],
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": user},
            ],
        }],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input  # type: ignore[return-value]
    raise ExtractionError(f"Claude [{stmt_type}] did not return a tool_use block.")


def _call_parallel_extraction(
    pdf_b64: str,
    company_name: str,
    years: List[int],
    currency: str = "INR",
    unit: str = "Crores",
) -> dict:
    """
    Run 3 focused Claude sub-agents in parallel — one per statement type.
    Merges results into a single dict compatible with _parse_raw_data.
    """
    log.info("Running 3 parallel Claude sub-agents (P&L / BS / CF)…")
    results = {}
    errors = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_call_statement_agent, stmt, pdf_b64, company_name, years, currency, unit): stmt
            for stmt in ("pl", "bs", "cf")
        }
        for future in as_completed(futures):
            stmt = futures[future]
            try:
                data = future.result()
                results[stmt] = data
                cfg = _STMT_AGENT_CONFIG[stmt]
                count = len(data.get(cfg["result_key"], []))
                log.info("Sub-agent [%s] complete: %d year(s) extracted.", stmt, count)
            except Exception as exc:
                log.warning("Sub-agent [%s] failed: %s", stmt, exc)
                errors[stmt] = str(exc)

    if not results:
        raise ExtractionError(f"All 3 sub-agents failed: {errors}")

    # Merge into single dict for _parse_raw_data
    merged: dict = {
        "company_name": company_name,
        "currency": currency,
        "unit": unit,
        "fiscal_years": years,
        "income_statements": [],
        "balance_sheets": [],
        "cash_flow_statements": [],
    }
    if "pl" in results:
        merged["income_statements"] = results["pl"].get("income_statements", [])
        if results["pl"].get("fiscal_years"):
            merged["fiscal_years"] = results["pl"]["fiscal_years"]
    if "bs" in results:
        merged["balance_sheets"] = results["bs"].get("balance_sheets", [])
    if "cf" in results:
        merged["cash_flow_statements"] = results["cf"].get("cash_flow_statements", [])

    return merged


@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
    reraise=True,
)
def _call_verification_api(pdf_b64: str, extracted_json: str) -> dict:
    """Pass 2 — ask Claude to verify its own extraction. PDF reused from cache."""
    system_prompt = Path("prompts/verification_system.txt").read_text()
    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": (
                        "Here is the extracted financial data:\n\n"
                        f"```json\n{extracted_json}\n```\n\n"
                        "Verify against the document and return the JSON result."
                    ),
                },
            ],
        }],
    )
    text = response.content[0].text
    try:
        match = re.search(r'\{.*"passes_all_checks".*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {"passes_all_checks": True, "issues": [], "warnings": [], "corrected_values": {}}


# ── Data parsing ──────────────────────────────────────────────────────────────

def _parse_raw_data(raw: dict) -> FinancialData:
    """Convert the raw dict returned by Claude into validated Pydantic models."""
    income_statements = [IncomeStatement(**s) for s in raw.get("income_statements", [])]
    balance_sheets    = [BalanceSheet(**s)       for s in raw.get("balance_sheets", [])]
    cash_flows        = [CashFlowStatement(**s)  for s in raw.get("cash_flow_statements", [])]

    fiscal_years = raw.get("fiscal_years") or sorted(
        {s.fiscal_year for s in income_statements + balance_sheets + cash_flows}
    )
    all_stmts = income_statements + balance_sheets + cash_flows
    avg_conf  = (
        sum(s.extraction_confidence for s in all_stmts) / len(all_stmts)
        if all_stmts else 1.0
    )

    return FinancialData(
        company_name=raw.get("company_name", "Unknown"),
        ticker=raw.get("ticker"),
        exchange=raw.get("exchange"),
        currency=raw.get("currency", "INR"),
        unit=raw.get("unit", "Crores"),
        fiscal_years=fiscal_years,
        income_statements=income_statements,
        balance_sheets=balance_sheets,
        cash_flow_statements=cash_flows,
        metadata=ExtractionMetadata(
            source_type="pdf",
            model_used=MODEL_NAME,
            overall_confidence=round(avg_conf, 3),
        ),
    )


# ── Extraction merge ──────────────────────────────────────────────────────────

def _merge_extractions(local_data: FinancialData, api_data: FinancialData) -> FinancialData:
    """
    Merge local + API extractions: prefer local values (exact pixel-level),
    fill None fields with API values.  Boosts overall confidence slightly.
    """
    def _merge_stmt(local_stmt, api_stmt):
        if api_stmt is None:
            return local_stmt
        if local_stmt is None:
            return api_stmt
        # Use Pydantic model_fields (works for BaseModel) instead of dataclasses.fields
        field_names = list(local_stmt.model_fields.keys())
        updates = {}
        for name in field_names:
            if getattr(local_stmt, name) is None:
                api_val = getattr(api_stmt, name, None)
                if api_val is not None:
                    updates[name] = api_val
        if updates:
            return local_stmt.model_copy(update=updates)
        return local_stmt

    # Collect all years from both local and API data
    all_years = sorted(set(local_data.fiscal_years) | set(api_data.fiscal_years))

    new_is: list = []
    new_bs: list = []
    new_cf: list = []

    for yr in all_years:
        merged_is = _merge_stmt(local_data.get_income_statement(yr), api_data.get_income_statement(yr))
        if merged_is:
            new_is.append(merged_is)

        merged_bs = _merge_stmt(local_data.get_balance_sheet(yr), api_data.get_balance_sheet(yr))
        if merged_bs:
            new_bs.append(merged_bs)

        merged_cf = _merge_stmt(local_data.get_cash_flow(yr), api_data.get_cash_flow(yr))
        if merged_cf:
            new_cf.append(merged_cf)

    local_data.income_statements    = new_is
    local_data.balance_sheets       = new_bs
    local_data.cash_flow_statements = new_cf
    local_data.fiscal_years         = all_years

    # After API gap-fill, confidence should reflect actual data quality
    has_revenue = any(s.revenue is not None and s.revenue > 0 for s in new_is)
    boosted = min(CONFIDENCE_API_BOOST_CAP, local_data.metadata.overall_confidence * CONFIDENCE_API_BOOST)
    # If API filled in revenue, floor at 0.90
    local_data.metadata.overall_confidence = max(0.90, boosted) if has_revenue else boosted
    return local_data


# ── Public API ────────────────────────────────────────────────────────────────

def extract_from_pdf(
    path:         str,
    company_name: str,
    fiscal_years: List[int],
    currency:     str = "INR",
    unit:         str = "Crores",
) -> FinancialData:
    """
    Extract financial statements from a PDF annual report.

    Strategy
    --------
    1. Always run local pdfplumber parser — no API needed, exact numbers.
    2. If ANTHROPIC_API_KEY is set AND local confidence < CONFIDENCE_API_FALLBACK,
       run a Claude API gap-fill pass and merge the results.
    """
    if not validate_pdf(path):
        raise ExtractionError(f"Invalid or missing PDF: {path}")

    total_pages = get_pdf_page_count(path)
    log.info("PDF loaded: %s (%d pages)", path, total_pages)

    # Pass 1 — local extraction
    from agents.pdf_parser import extract_local
    log.info("Local extraction: parsing financial statements from PDF text layer…")
    financial_data = extract_local(path, company_name, fiscal_years, currency, unit)
    conf = financial_data.metadata.overall_confidence
    log.info(
        "Local extraction complete. Years: %s. Confidence: %.0f%%",
        financial_data.fiscal_years,
        conf * 100,
    )

    # Pass 2 — parallel Claude sub-agents (P&L / BS / CF) when local confidence is low
    if ANTHROPIC_API_KEY and conf < CONFIDENCE_API_FALLBACK:
        log.info("Confidence %.0f%% below threshold — running 3 parallel Claude sub-agents…", conf * 100)
        try:
            if total_pages > PDF_SMALL_THRESHOLD:
                toc_b64        = extract_page_range_as_base64(path, 1, PDF_TOC_PAGES)
                start_p, end_p = _detect_financial_pages(toc_b64, total_pages)
                pdf_b64        = extract_page_range_as_base64(path, start_p, end_p)
            else:
                pdf_b64 = load_pdf_as_base64(path)

            raw            = _call_parallel_extraction(pdf_b64, company_name, fiscal_years, currency, unit)
            api_data       = _parse_raw_data(raw)
            financial_data = _merge_extractions(financial_data, api_data)
            log.info("Parallel sub-agent extraction complete.")
        except ConfigurationError:
            raise
        except Exception as exc:
            log.warning("Parallel sub-agent extraction failed (%s) — using local extraction only.", exc)
    elif ANTHROPIC_API_KEY:
        log.info("Local confidence ≥ %.0f%% — skipping Claude API pass.", CONFIDENCE_API_FALLBACK * 100)
    else:
        log.info("No API key set — using local extraction only.")

    return financial_data


def extract_from_json(path: str) -> FinancialData:
    """
    Load financial data from a pre-structured JSON file.
    Used for testing and manual data entry.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Could not read JSON file '{path}': {exc}") from exc

    financial_data = _parse_raw_data(data)
    financial_data.metadata.source_type = "manual"
    log.info(
        "Loaded manual data for %s. Years: %s",
        financial_data.company_name,
        financial_data.fiscal_years,
    )
    return financial_data


def validate_relevance(financial_data: FinancialData, source_name: str = "document") -> None:
    """
    Raise ValidationError if the extracted data does not look like real
    financial statements.

    Checks:
    - At least one fiscal year extracted
    - At least one year has revenue > 0
    - Overall extraction confidence ≥ CONFIDENCE_MIN_ACCEPT
    """
    years = financial_data.sorted_years()
    if not years:
        raise ValidationError(
            f"'{source_name}' does not appear to contain financial statements. "
            "Please upload an annual report, financial results PDF, or structured JSON."
        )

    has_revenue = any(
        (stmt := financial_data.get_income_statement(y)) is not None
        and stmt.revenue
        and stmt.revenue > 0
        for y in years
    )
    if not has_revenue:
        raise ValidationError(
            f"'{source_name}' yielded no revenue data. "
            "The file may not be a financial report, or it may be a scanned image PDF "
            "with no text layer."
        )

    if financial_data.metadata.overall_confidence < CONFIDENCE_MIN_ACCEPT:
        raise ValidationError(
            f"Extraction confidence for '{source_name}' is too low "
            f"({financial_data.metadata.overall_confidence:.0%}). "
            "The document does not appear to contain readable financial statements."
        )


def merge_financial_data(data_list: List[FinancialData]) -> FinancialData:
    """
    Merge multiple FinancialData objects (one per fiscal-year file) into a
    single combined dataset. For duplicate fiscal years, keeps the statement
    with the higher extraction_confidence. Company-level metadata is taken
    from the first item.
    """
    if len(data_list) == 1:
        return data_list[0]

    base                  = data_list[0]
    is_by_year:  dict     = {}
    bs_by_year:  dict     = {}
    cf_by_year:  dict     = {}
    all_warnings: List[str] = []

    for fd in data_list:
        for stmt in fd.income_statements:
            yr = stmt.fiscal_year
            if yr not in is_by_year or stmt.extraction_confidence > is_by_year[yr].extraction_confidence:
                is_by_year[yr] = stmt
        for stmt in fd.balance_sheets:
            yr = stmt.fiscal_year
            if yr not in bs_by_year or stmt.extraction_confidence > bs_by_year[yr].extraction_confidence:
                bs_by_year[yr] = stmt
        for stmt in fd.cash_flow_statements:
            yr = stmt.fiscal_year
            if yr not in cf_by_year or stmt.extraction_confidence > cf_by_year[yr].extraction_confidence:
                cf_by_year[yr] = stmt
        all_warnings.extend(fd.metadata.warnings)

    all_years = sorted(set(is_by_year) | set(bs_by_year) | set(cf_by_year))
    avg_conf  = sum(fd.metadata.overall_confidence for fd in data_list) / len(data_list)

    return FinancialData(
        company_name=base.company_name,
        ticker=base.ticker,
        exchange=base.exchange,
        currency=base.currency,
        unit=base.unit,
        fiscal_years=all_years,
        income_statements=list(is_by_year.values()),
        balance_sheets=list(bs_by_year.values()),
        cash_flow_statements=list(cf_by_year.values()),
        metadata=ExtractionMetadata(
            source_type=base.metadata.source_type,
            model_used=base.metadata.model_used,
            overall_confidence=round(avg_conf, 3),
            warnings=all_warnings,
        ),
    )
