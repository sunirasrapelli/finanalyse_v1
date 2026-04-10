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
    from dataclasses import fields as dc_fields

    def _merge_stmt(local_stmt, api_stmt):
        if api_stmt is None:
            return local_stmt
        if local_stmt is None:
            return api_stmt
        for f in dc_fields(local_stmt):
            if getattr(local_stmt, f.name) is None:
                api_val = getattr(api_stmt, f.name)
                if api_val is not None:
                    object.__setattr__(local_stmt, f.name, api_val)
        return local_stmt

    for yr in local_data.fiscal_years:
        orig_is   = local_data.get_income_statement(yr)
        merged_is = _merge_stmt(orig_is, api_data.get_income_statement(yr))
        if merged_is and (id(merged_is) != id(orig_is)):
            local_data.income_statements.append(merged_is)

        orig_bs   = local_data.get_balance_sheet(yr)
        merged_bs = _merge_stmt(orig_bs, api_data.get_balance_sheet(yr))
        if merged_bs and (id(merged_bs) != id(orig_bs)) and merged_bs not in local_data.balance_sheets:
            local_data.balance_sheets.append(merged_bs)

        orig_cf   = local_data.get_cash_flow(yr)
        merged_cf = _merge_stmt(orig_cf, api_data.get_cash_flow(yr))
        if merged_cf and (id(merged_cf) != id(orig_cf)) and merged_cf not in local_data.cash_flow_statements:
            local_data.cash_flow_statements.append(merged_cf)

    local_data.metadata.overall_confidence = min(
        CONFIDENCE_API_BOOST_CAP,
        local_data.metadata.overall_confidence * CONFIDENCE_API_BOOST,
    )
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

    # Pass 2 — optional Claude API gap-fill
    if ANTHROPIC_API_KEY and conf < CONFIDENCE_API_FALLBACK:
        log.info("Confidence below %.0f%% — running Claude API gap-fill…", CONFIDENCE_API_FALLBACK * 100)
        try:
            if total_pages > PDF_SMALL_THRESHOLD:
                toc_b64       = extract_page_range_as_base64(path, 1, PDF_TOC_PAGES)
                start_p, end_p = _detect_financial_pages(toc_b64, total_pages)
                pdf_b64       = extract_page_range_as_base64(path, start_p, end_p)
            else:
                pdf_b64 = load_pdf_as_base64(path)

            raw      = _call_extraction_api(pdf_b64, company_name, fiscal_years, currency, unit)
            api_data = _parse_raw_data(raw)
            financial_data = _merge_extractions(financial_data, api_data)
            log.info("Claude API gap-fill complete.")
        except ConfigurationError:
            raise
        except Exception as exc:
            log.warning("Claude API gap-fill failed (%s) — using local extraction only.", exc)
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
