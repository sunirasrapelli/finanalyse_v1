import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.parent
OUTPUTS_DIR = BASE_DIR / "outputs"
EXCEL_DIR   = OUTPUTS_DIR / "excel"
REPORTS_DIR = OUTPUTS_DIR / "reports"
LOGS_DIR    = OUTPUTS_DIR / "logs"

for _d in (EXCEL_DIR, REPORTS_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Anthropic ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str   = os.getenv("ANTHROPIC_API_KEY", "")
MODEL_NAME:        str   = "claude-sonnet-4-6"
MAX_TOKENS:        int   = 8192
RETRY_ATTEMPTS:    int   = 3
RETRY_WAIT_MIN:    float = 2.0
RETRY_WAIT_MAX:    float = 10.0

# ── PDF Handling ─────────────────────────────────────────────────────────────
# Pages sent whole when ≤ this threshold; above it we first detect
# which pages hold the financial statements via a TOC scan.
PDF_SMALL_THRESHOLD: int = 60
PDF_TOC_PAGES:       int = 15   # page count sent for TOC detection

# ── Extraction Quality Thresholds ────────────────────────────────────────────
# Below FALLBACK we run a Claude API verification / gap-fill pass.
CONFIDENCE_API_FALLBACK: float = 0.75
# Below MIN_ACCEPT we reject the document outright.
CONFIDENCE_MIN_ACCEPT:   float = 0.25
# After a successful API gap-fill we bump confidence by this multiplier,
# capped at BOOST_CAP so we never claim perfect certainty.
CONFIDENCE_API_BOOST:    float = 1.10
CONFIDENCE_API_BOOST_CAP: float = 0.95

# ── Web / Upload Limits ──────────────────────────────────────────────────────
MAX_UPLOAD_SIZE_BYTES: int = 50 * 1024 * 1024   # 50 MB per file
MAX_UPLOAD_FILES:      int = 10                  # files per request
CHAT_MAX_HISTORY_PAIRS: int = 20                 # message pairs retained
ERROR_MSG_MAX_LENGTH:   int = 300                # chars shown in UI errors

# ── Financial Valuation Defaults ─────────────────────────────────────────────
RISK_FREE_RATE:       float = 0.067   # 6.7%  — Indian 10Y G-Sec
EQUITY_RISK_PREMIUM:  float = 0.055   # 5.5%
DEFAULT_BETA:         float = 1.0
CORPORATE_TAX_RATE:   float = 0.25    # 25%   — India base rate
TERMINAL_GROWTH_RATE: float = 0.04    # 4%

# ── Excel Visual Theme ───────────────────────────────────────────────────────
COLOR_NAVY         = "#1F3864"
COLOR_GOLD         = "#C9A84C"
COLOR_LIGHT_BLUE   = "#EBF3FB"
COLOR_WHITE        = "#FFFFFF"
COLOR_PASS_GREEN   = "#C6EFCE"
COLOR_FAIL_RED     = "#FFC7CE"
COLOR_SECTION_GRAY = "#D9D9D9"
