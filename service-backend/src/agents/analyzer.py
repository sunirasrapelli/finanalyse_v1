"""
Analyzer Agent — AI commentary and next-step generation.

Exposes two public functions:
  generate_commentary(financial_data) -> Dict[str, str]
  generate_next_steps(financial_data, commentary) -> List[Dict[str, str]]

Both call Claude via the Anthropic SDK and retry up to RETRY_ATTEMPTS times
on transient failures.
"""
import json
import threading
from typing import Any, Dict, List, Optional

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import (
    ANTHROPIC_API_KEY,
    MAX_TOKENS,
    MODEL_NAME,
    RETRY_ATTEMPTS,
    RETRY_WAIT_MAX,
    RETRY_WAIT_MIN,
)
from errors import AnalysisError, ConfigurationError
from models.company_data import FinancialData
from utils.logger import get_logger

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
                        "ANTHROPIC_API_KEY is not set — cannot generate commentary."
                    )
                _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ── JSON parsing helper ───────────────────────────────────────────────────────

def _parse_json_response(text: str) -> Any:
    """
    Strip optional Markdown code fences then parse as JSON.
    Raises AnalysisError on malformed responses instead of leaking ValueError.
    """
    s = text.strip()
    if s.startswith("```"):
        # Drop opening fence (```json or ```)
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        # Drop closing fence
        if s.endswith("```"):
            s = s[:-3]
    try:
        return json.loads(s)
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"Claude returned malformed JSON: {exc}") from exc


# ── Data summary builder ──────────────────────────────────────────────────────

def _build_data_summary(fd: FinancialData) -> str:
    """Serialise key financial metrics into compact JSON for the prompt."""
    years = fd.sorted_years()
    summary: Dict[str, Any] = {
        "company":        fd.company_name,
        "ticker":         fd.ticker,
        "currency":       fd.currency,
        "unit":           fd.unit,
        "fiscal_years":   years,
        "income_statement": {},
        "balance_sheet":    {},
        "cash_flow":        {},
    }

    for yr in years:
        is_s = fd.get_income_statement(yr)
        bs_s = fd.get_balance_sheet(yr)
        cf_s = fd.get_cash_flow(yr)

        if is_s:
            summary["income_statement"][yr] = {
                "revenue":                 is_s.revenue,
                "ebitda":                  is_s.ebitda,
                "ebit":                    is_s.ebit,
                "pat":                     is_s.pat,
                "interest_expense":        is_s.interest_expense,
                "depreciation_amortization": is_s.depreciation_amortization,
            }
        if bs_s:
            total_debt = (bs_s.long_term_debt or 0) + (bs_s.short_term_borrowings or 0)
            net_debt   = total_debt - (bs_s.cash_and_equivalents or 0) - (
                bs_s.short_term_investments or 0
            )
            summary["balance_sheet"][yr] = {
                "total_assets":  bs_s.total_assets,
                "total_equity":  bs_s.total_equity,
                "total_debt":    total_debt,
                "net_debt":      net_debt,
                "working_capital": (bs_s.total_current_assets or 0) - (
                    bs_s.total_current_liabilities or 0
                ),
            }
        if cf_s:
            summary["cash_flow"][yr] = {
                "cfo":   cf_s.cash_from_operations,
                "capex": cf_s.capex,
                "fcf":   cf_s.free_cash_flow,
            }

    # Derived ratios for the latest year
    latest = years[-1] if years else None
    if latest:
        is_l = fd.get_income_statement(latest)
        bs_l = fd.get_balance_sheet(latest)
        if is_l and bs_l and is_l.revenue:
            total_debt_l = (bs_l.long_term_debt or 0) + (bs_l.short_term_borrowings or 0)
            summary["latest_ratios"] = {
                "gross_margin":  round((is_l.gross_profit or 0) / is_l.revenue, 3)
                                 if is_l.gross_profit else None,
                "ebitda_margin": round((is_l.ebitda or 0) / is_l.revenue, 3)
                                 if is_l.ebitda else None,
                "net_margin":    round((is_l.pat or 0) / is_l.revenue, 3)
                                 if is_l.pat else None,
                "roe":           round((is_l.pat or 0) / (bs_l.total_equity or 1), 3)
                                 if bs_l.total_equity else None,
                "roa":           round((is_l.pat or 0) / (bs_l.total_assets or 1), 3)
                                 if bs_l.total_assets else None,
                "de_ratio":      round(total_debt_l / (bs_l.total_equity or 1), 2)
                                 if bs_l.total_equity else None,
            }

    return json.dumps(summary, indent=2, default=str)


# ── Prompts ───────────────────────────────────────────────────────────────────

_COMMENTARY_SYSTEM = """\
You are a senior equity research analyst at a top-tier investment bank.
Write precise, insightful, data-driven commentary in a professional style.
Rules:
- Lead each section with the most important insight
- Reference specific numbers (margins %, growth rates, ratios) with context
- Note multi-year trends — improving, declining, stable
- Highlight risks and strengths
- 2–3 concise paragraphs per section
- No filler phrases ("it can be seen that…")
- Write in present tense
"""

_COMMENTARY_USER = """\
Analyse the following financial data and produce commentary for each section.
Return a JSON object with exactly these keys:
{{
  "executive_summary":      "2-3 paragraphs",
  "revenue_analysis":       "2 paragraphs",
  "profitability_analysis": "2 paragraphs",
  "balance_sheet_analysis": "2 paragraphs",
  "cash_flow_analysis":     "2 paragraphs",
  "key_risks":     "3–4 bullet points, each starting with •, newline-separated",
  "key_strengths": "3–4 bullet points, each starting with •, newline-separated"
}}

Financial Data:
{data}
"""

_NEXT_STEPS_SYSTEM = """\
You are a senior equity research analyst at a top-tier investment bank.
Based on a completed financial analysis, recommend the most important next
actions for an analyst or investor. Be specific and ground every item in the
actual numbers from the data.
"""

_NEXT_STEPS_USER = """\
Based on the financial data and executive summary below, recommend next steps.

Return a JSON array with EXACTLY 6 items. Each item must have exactly these keys:
[
  {{
    "title":       "5-8 word action phrase",
    "description": "2 sentences max — specific, referencing actual figures",
    "priority":    "high" | "medium" | "low"
  }},
  ...
]

Requirements:
- At least 1 high, 2 medium, and 1 low priority item
- Every description must cite specific numbers from the data
- No generic advice

Financial Data:
{data}

Executive Summary:
{executive_summary}

Key Risks:
{key_risks}
"""


# ── Public API ────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
    reraise=True,
)
def generate_commentary(financial_data: FinancialData) -> Dict[str, str]:
    """
    Call Claude to generate investment-banking-style commentary sections.

    Returns a dict with keys: executive_summary, revenue_analysis,
    profitability_analysis, balance_sheet_analysis, cash_flow_analysis,
    key_risks, key_strengths.

    Raises AnalysisError on failure (no silent fallback — callers decide
    whether to surface the error or substitute placeholder text).
    """
    log.info("Generating financial commentary via Claude API…")
    data_summary = _build_data_summary(financial_data)
    user_prompt  = _COMMENTARY_USER.format(data=data_summary)

    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=3000,
        system=_COMMENTARY_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    commentary: Dict[str, str] = _parse_json_response(response.content[0].text)
    log.info("Commentary generated successfully.")
    return commentary


@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
    reraise=True,
)
def generate_next_steps(
    financial_data: FinancialData,
    commentary:     Dict[str, str],
) -> List[Dict[str, str]]:
    """
    Call Claude to generate exactly 6 prioritised next-step recommendations.

    Returns a list of dicts with keys: title, description, priority.
    Raises AnalysisError on failure.
    """
    log.info("Generating next steps via Claude API…")
    data_summary = _build_data_summary(financial_data)
    user_prompt  = _NEXT_STEPS_USER.format(
        data=data_summary,
        executive_summary=commentary.get("executive_summary", ""),
        key_risks=commentary.get("key_risks", ""),
    )

    response = _get_client().messages.create(
        model=MODEL_NAME,
        max_tokens=1500,
        system=_NEXT_STEPS_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    next_steps: List[Dict[str, str]] = _parse_json_response(response.content[0].text)
    log.info("Next steps generated: %d items.", len(next_steps))
    return next_steps
