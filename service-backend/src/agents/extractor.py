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
    render_pdf_pages_to_images,
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


# Income Statement keyword set for page scanning
_IS_KEYWORDS = frozenset([
    "revenue", "total income", "net sales", "turnover",
    "profit after tax", "profit before tax", "net profit",
    "earnings before", "ebitda", "operating income",
])

# Max images per Claude vision request (API hard limit is 20)
_VISION_MAX_PAGES = 20


@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
    reraise=True,
)
def _call_extraction_api_images(
    path:         str,
    company_name: str,
    years:        List[int],
    currency:     str = "INR",
    unit:         str = "Crores",
) -> dict:
    """
    Vision-based fallback extraction.

    Renders PDF pages that contain Income Statement keywords as JPEG images
    and sends them to Claude with the same tool_use schema.  Used when the
    document-API gap-fill completes but still returns no revenue data.
    """
    import pdfplumber

    log.info("Vision fallback — scanning pages for IS keywords…")

    # Scan every page for IS-related text to pick candidate pages
    candidate_pages: List[int] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").lower()
            if any(kw in text for kw in _IS_KEYWORDS):
                candidate_pages.append(i)

    # If pdfplumber found nothing with IS keywords, fall back to the first half
    # of the document (IS usually appears before BS in annual reports)
    if not candidate_pages:
        total = get_pdf_page_count(path)
        mid   = max(1, total // 2)
        candidate_pages = list(range(1, min(mid + 1, _VISION_MAX_PAGES + 1)))
        log.info("No IS keyword pages found — using pages 1-%d as candidates.", candidate_pages[-1])
    else:
        log.info("IS keyword pages: %s", candidate_pages[:_VISION_MAX_PAGES])

    pages_to_render = candidate_pages[:_VISION_MAX_PAGES]

    # Render candidate pages as JPEG images
    images_b64 = render_pdf_pages_to_images(path, pages_to_render, dpi=150)
    log.info("Rendered %d page(s) as images for vision extraction.", len(images_b64))

    # Build vision content: one image block per page, then the prompt
    content: list = []
    for img_b64 in images_b64:
        content.append({
            "type":   "image",
            "source": {
                "type":       "base64",
                "media_type": "image/jpeg",
                "data":       img_b64,
            },
        })

    system_prompt = Path("prompts/extraction_system.txt").read_text()
    user_template = Path("prompts/extraction_user.txt").read_text()
    user_prompt   = user_template.format(
        company_name=company_name,
        years=", ".join(str(y) for y in years),
        currency=currency,
        unit=unit,
    )
    content.append({"type": "text", "text": user_prompt})

    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        tools=[EXTRACTION_TOOL],
        tool_choice=TOOL_CHOICE,
        messages=[{"role": "user", "content": content}],
    )

    for block in response.content:
        if block.type == "tool_use":
            return block.input  # type: ignore[return-value]
    raise ExtractionError("Vision fallback: Claude did not return a tool_use block.")


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
        # Use Pydantic model_fields (works for BaseModel subclasses)
        for field_name in type(local_stmt).model_fields:
            if getattr(local_stmt, field_name) is None:
                api_val = getattr(api_stmt, field_name, None)
                if api_val is not None:
                    setattr(local_stmt, field_name, api_val)
        return local_stmt

    # Merge for all years found by either source
    all_years = sorted(set(local_data.fiscal_years) | set(api_data.fiscal_years))
    for yr in all_years:
        orig_is   = local_data.get_income_statement(yr)
        merged_is = _merge_stmt(orig_is, api_data.get_income_statement(yr))
        if merged_is is not None and (orig_is is None or id(merged_is) != id(orig_is)):
            if orig_is is None:
                local_data.income_statements.append(merged_is)

        orig_bs   = local_data.get_balance_sheet(yr)
        merged_bs = _merge_stmt(orig_bs, api_data.get_balance_sheet(yr))
        if merged_bs is not None and (orig_bs is None or id(merged_bs) != id(orig_bs)):
            if orig_bs is None:
                local_data.balance_sheets.append(merged_bs)

        orig_cf   = local_data.get_cash_flow(yr)
        merged_cf = _merge_stmt(orig_cf, api_data.get_cash_flow(yr))
        if merged_cf is not None and (orig_cf is None or id(merged_cf) != id(orig_cf)):
            if orig_cf is None:
                local_data.cash_flow_statements.append(merged_cf)

    # Update fiscal_years to include any new years added from API
    local_data.fiscal_years = sorted(set(
        local_data.fiscal_years
        + [s.fiscal_year for s in local_data.income_statements]
        + [s.fiscal_year for s in local_data.balance_sheets]
        + [s.fiscal_year for s in local_data.cash_flow_statements]
    ))

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

    # Pass 2 — optional Claude API gap-fill (document-based)
    # Trigger if confidence is low OR if revenue data is completely missing
    years = financial_data.sorted_years()

    def _check_has_revenue(fd: "FinancialData") -> bool:
        return any(
            (stmt := fd.get_income_statement(y)) is not None
            and stmt.revenue and stmt.revenue > 0
            for y in fd.sorted_years()
        )

    has_revenue    = _check_has_revenue(financial_data)
    needs_gap_fill = conf < CONFIDENCE_API_FALLBACK or not has_revenue

    if ANTHROPIC_API_KEY and needs_gap_fill:
        reason = (
            "no revenue data found"
            if not has_revenue and conf >= CONFIDENCE_API_FALLBACK
            else f"confidence {conf:.0%} < {CONFIDENCE_API_FALLBACK:.0%}"
        )
        log.info("Running Claude API gap-fill (%s)…", reason)
        try:
            if total_pages > PDF_SMALL_THRESHOLD:
                toc_b64        = extract_page_range_as_base64(path, 1, PDF_TOC_PAGES)
                start_p, end_p = _detect_financial_pages(toc_b64, total_pages)
                pdf_b64        = extract_page_range_as_base64(path, start_p, end_p)
            else:
                pdf_b64 = load_pdf_as_base64(path)

            raw            = _call_extraction_api(pdf_b64, company_name, fiscal_years, currency, unit)
            api_data       = _parse_raw_data(raw)
            financial_data = _merge_extractions(financial_data, api_data)
            log.info("Claude API gap-fill complete.")
        except ConfigurationError:
            raise
        except Exception as exc:
            log.warning("Claude API gap-fill failed — using local extraction only.", exc_info=True)

        # Pass 3 — vision fallback if document API gap-fill still found no revenue
        if not _check_has_revenue(financial_data):
            log.info("Document API gap-fill returned no revenue — trying vision fallback…")
            try:
                raw_vis        = _call_extraction_api_images(
                    path, company_name, fiscal_years, currency, unit
                )
                vis_data       = _parse_raw_data(raw_vis)
                financial_data = _merge_extractions(financial_data, vis_data)
                log.info("Vision fallback complete.")
            except ConfigurationError:
                raise
            except Exception as exc:
                log.warning("Vision fallback failed — proceeding with available data.", exc_info=True)

    elif ANTHROPIC_API_KEY:
        log.info(
            "Local confidence >= %.0f%% with revenue present — skipping Claude API pass.",
            CONFIDENCE_API_FALLBACK * 100,
        )
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
