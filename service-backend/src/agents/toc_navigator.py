"""
TOC Navigator Agent

Identifies the page range of Consolidated Financial Statements
in an Indian annual report PDF using 3 layered strategies:

  Layer 1 - pdfplumber word-position scan  (no API cost, ~10 ms)
  Layer 2 - pypdf /GoTo hyperlink resolver  (no API cost, ~20 ms)
  Layer 3 - Claude API on TOC pages         (fallback, uses tokens)

All layers return a TOCResult. The first success wins.
"""
import json
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pdfplumber
from pypdf import PdfReader

from config.settings import ANTHROPIC_API_KEY, MODEL_NAME
from utils.logger import get_logger
from utils.pdf_handler import extract_page_range_as_base64, get_pdf_page_count

log = get_logger(__name__)

# How many pages to inspect for the TOC
TOC_SCAN_PAGES = 12

# Regex: matches any "Consolidated ..." heading that indicates the FS section
_CONSOL_RE = re.compile(
    r"consolidated\s+(?:financial\s+statements?|balance\s+sheet|accounts?|statement)",
    re.IGNORECASE,
)

# Regex to parse a full TOC line:
#   "Consolidated Financial Statements .......... 145"
#   "Consolidated Financial Statements   145"
#   "Consolidated Balance Sheet                145"
_TOC_LINE_RE = re.compile(
    r"(consolidated\s+(?:financial\s+statements?|balance\s+sheet|accounts?|statement)"
    r"[^\n\d]*?)"       # rest of label (no digits, no newlines)
    r"[\s.]{1,60}"      # dots or spaces
    r"(\d{1,4})"        # page number
    r"\s*(?:\n|$)",
    re.IGNORECASE,
)

# Pattern to find standalone / next section (detects end of CFS section in TOC)
_NEXT_SECTION_RE = re.compile(
    r"^(?:standalone|notice|directors|annexure|independent\s+auditors)[^\n]*[\s.]+(\d{1,4})\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Typical max length of a CFS section in Indian annual reports
_CFS_MAX_PAGES = 90


@dataclass
class TOCResult:
    section_name: str
    start_page: int
    end_page: int
    method: str           # "word_position" | "hyperlink" | "claude_api" | "fallback"
    toc_page: Optional[int] = None


# ---------------------------------------------------------------------------
# Layer 1 - pdfplumber word-position scan
# ---------------------------------------------------------------------------

def _words_on_line(words: list, y_center: float, y_tol: float = 6.0) -> list:
    """Return words whose vertical center is within y_tol of y_center."""
    return [w for w in words if abs((w["top"] + w["bottom"]) / 2 - y_center) <= y_tol]


def _try_word_position(path: str, total_pages: int) -> Optional[TOCResult]:
    """
    Scan TOC pages with pdfplumber. For each page extract words and look for
    a "Consolidated ..." label on the left and a page-number digit cluster on
    the right of the same text line.
    """
    try:
        with pdfplumber.open(path) as pdf:
            for pg_idx in range(min(TOC_SCAN_PAGES, len(pdf.pages))):
                page = pdf.pages[pg_idx]
                page_width = float(page.width or 595)

                # -- Method A: full-page text regex (fast path) --
                text = page.extract_text(layout=True) or ""
                m = _TOC_LINE_RE.search(text)
                if m:
                    section_name = m.group(1).strip()
                    start_page = int(m.group(2))
                    # Detect end page from next major section in same text blob
                    end_page = _end_page_from_text(text, m.end(), start_page, total_pages)
                    log.info(
                        "TOC Layer 1 (text regex): '%s' pages %d-%d (toc_page=%d)",
                        section_name, start_page, end_page, pg_idx + 1,
                    )
                    return TOCResult(
                        section_name=section_name,
                        start_page=start_page,
                        end_page=end_page,
                        method="word_position",
                        toc_page=pg_idx + 1,
                    )

                # -- Method B: word-level matching (handles right-aligned numbers) --
                words = page.extract_words(x_tolerance=3, y_tolerance=3) or []
                for w in words:
                    if not _CONSOL_RE.search(w["text"]):
                        continue
                    # Find the rightmost number on the same text line
                    y_mid = (w["top"] + w["bottom"]) / 2
                    line_words = _words_on_line(words, y_mid)
                    # Number candidates: right side of page, purely digits
                    nums = [
                        lw for lw in line_words
                        if re.fullmatch(r"\d{1,4}", lw["text"])
                        and float(lw["x0"]) > page_width * 0.55
                    ]
                    if not nums:
                        # Page number might be on same line but slightly below; expand tol
                        nums = [
                            lw for lw in _words_on_line(words, y_mid, y_tol=14)
                            if re.fullmatch(r"\d{1,4}", lw["text"])
                            and float(lw["x0"]) > page_width * 0.55
                        ]
                    if nums:
                        start_page = int(max(nums, key=lambda lw: float(lw["x0"]))["text"])
                        # Collect the full label from this line
                        label_words = sorted(
                            [lw for lw in line_words if float(lw["x1"]) <= page_width * 0.75],
                            key=lambda lw: float(lw["x0"]),
                        )
                        section_name = " ".join(lw["text"] for lw in label_words).strip()
                        end_page = _end_page_from_text(text, 0, start_page, total_pages)
                        log.info(
                            "TOC Layer 1 (word-pos): '%s' pages %d-%d (toc_page=%d)",
                            section_name, start_page, end_page, pg_idx + 1,
                        )
                        return TOCResult(
                            section_name=section_name,
                            start_page=start_page,
                            end_page=end_page,
                            method="word_position",
                            toc_page=pg_idx + 1,
                        )
    except Exception as exc:
        log.debug("TOC Layer 1 failed: %s", exc)
    return None


def _end_page_from_text(text: str, search_from: int, start_page: int, total_pages: int) -> int:
    """
    Estimate end_page by finding the next major section's page number in the TOC text.
    Falls back to start_page + CFS_MAX_PAGES.
    """
    remaining = text[search_from:]
    m = _NEXT_SECTION_RE.search(remaining)
    if m:
        next_start = int(m.group(1))
        if next_start > start_page:
            return next_start - 1
    return min(total_pages, start_page + _CFS_MAX_PAGES)


# ---------------------------------------------------------------------------
# Layer 2 - pypdf /GoTo hyperlink resolver
# ---------------------------------------------------------------------------

def _build_page_id_map(reader: PdfReader) -> dict:
    """Map pypdf indirect-reference idnum -> 1-based page number."""
    page_id_map: dict = {}
    for i, page in enumerate(reader.pages):
        ref = getattr(page, "indirect_reference", None)
        if ref:
            page_id_map[ref.idnum] = i + 1
    return page_id_map


def _resolve_goto_dest(dest, page_id_map: dict) -> Optional[int]:
    """
    Resolve a /GoTo destination to a 1-based page number.
    dest may be a list [page_ref, /Fit, ...] or a named destination.
    """
    if hasattr(dest, "get_object"):
        dest = dest.get_object()
    if isinstance(dest, list) and len(dest) > 0:
        page_ref = dest[0]
        ref_id = getattr(page_ref, "idnum", None)
        if ref_id is not None:
            return page_id_map.get(ref_id)
    return None


def _try_hyperlink(path: str, total_pages: int) -> Optional[TOCResult]:
    """
    Layer 2: Use pypdf to read /Annots on TOC pages. For each /Link with a
    /GoTo action that points to a page in the latter half of the document,
    crop the annotation rect via pdfplumber to read the link text.
    """
    try:
        reader = PdfReader(path)
        page_id_map = _build_page_id_map(reader)

        with pdfplumber.open(path) as plumb_pdf:
            for pg_idx in range(min(TOC_SCAN_PAGES, len(reader.pages))):
                pypdf_page = reader.pages[pg_idx]
                plumb_page = plumb_pdf.pages[pg_idx]
                page_height = float(plumb_page.height or 842)

                annots = pypdf_page.get("/Annots")
                if not annots:
                    continue

                for annot_ref in annots:
                    try:
                        annot = annot_ref.get_object()
                        if annot.get("/Subtype") != "/Link":
                            continue

                        # Resolve /GoTo target page
                        target_page: Optional[int] = None
                        action = annot.get("/A")
                        if action:
                            a = action.get_object() if hasattr(action, "get_object") else action
                            if a.get("/S") == "/GoTo":
                                target_page = _resolve_goto_dest(a.get("/D"), page_id_map)

                        # Also try /Dest directly on the annotation
                        if target_page is None:
                            dest_direct = annot.get("/Dest")
                            if dest_direct is not None:
                                target_page = _resolve_goto_dest(dest_direct, page_id_map)

                        if target_page is None:
                            continue

                        # Only care about links that jump well into the document
                        if target_page < total_pages * 0.3:
                            continue

                        # Crop annotation bounding box with pdfplumber to get link text
                        rect = annot.get("/Rect")
                        if not rect:
                            continue
                        x0, y0_pdf, x1, y1_pdf = [float(v) for v in rect]
                        # PDF coords: y=0 at bottom; pdfplumber: y=0 at top
                        y0 = page_height - y1_pdf
                        y1 = page_height - y0_pdf
                        # Add small margin
                        crop = plumb_page.crop((
                            max(0, x0 - 2), max(0, y0 - 2),
                            min(float(plumb_page.width), x1 + 2),
                            min(page_height, y1 + 2),
                        ))
                        link_text = (crop.extract_text() or "").strip()

                        if _CONSOL_RE.search(link_text):
                            end_page = min(total_pages, target_page + _CFS_MAX_PAGES)
                            log.info(
                                "TOC Layer 2 (hyperlink): '%s' -> page %d (toc_page=%d)",
                                link_text, target_page, pg_idx + 1,
                            )
                            return TOCResult(
                                section_name=link_text or "Consolidated Financial Statements",
                                start_page=target_page,
                                end_page=end_page,
                                method="hyperlink",
                                toc_page=pg_idx + 1,
                            )
                    except Exception:
                        continue
    except Exception as exc:
        log.debug("TOC Layer 2 (hyperlink) failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Layer 3 - Claude API fallback
# ---------------------------------------------------------------------------

def _try_claude_api(path: str, total_pages: int) -> Optional[TOCResult]:
    """
    Layer 3: Send the first TOC_SCAN_PAGES to Claude and ask it to identify
    the Consolidated Financial Statements page range.
    """
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        scan_end = min(TOC_SCAN_PAGES, total_pages)
        toc_b64 = extract_page_range_as_base64(path, 1, scan_end)

        response = client.messages.create(
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
                            "data": toc_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is the table of contents / index of an Indian company annual report. "
                            "Find the entry for 'Consolidated Financial Statements' "
                            "(or 'Consolidated Balance Sheet' if that is the first entry). "
                            "Return ONLY a JSON object: "
                            '{"section_name": "...", "start_page": <int>, "end_page": <int>} '
                            "where end_page is the last page of the section "
                            "(one before the next major section such as Standalone statements or Annexures). "
                            "If not found, return the JSON literal null."
                        ),
                    },
                ],
            }],
        )
        text = response.content[0].text.strip()
        if text.lower().startswith("null"):
            return None
        match = re.search(r'\{[^{}]*"start_page"[^{}]*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            start = int(data["start_page"])
            end = int(data.get("end_page", min(start + _CFS_MAX_PAGES, total_pages)))
            section = data.get("section_name", "Consolidated Financial Statements")
            log.info("TOC Layer 3 (claude_api): '%s' pages %d-%d", section, start, end)
            return TOCResult(
                section_name=section,
                start_page=start,
                end_page=end,
                method="claude_api",
            )
    except Exception as exc:
        log.warning("TOC Layer 3 (claude_api) failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def navigate_to_consolidated_fs(path: str) -> TOCResult:
    """
    Identify the Consolidated Financial Statements page range in a PDF.

    Tries 3 strategies in order (cheapest first):
      1. pdfplumber word-position scan  (no API cost)
      2. pypdf /GoTo hyperlink resolver (no API cost)
      3. Claude API on TOC pages        (token cost, reliable fallback)

    If all fail, returns a conservative fallback using the last third of the PDF.
    """
    total_pages = get_pdf_page_count(path)
    log.info("TOC Navigator: '%s' (%d pages)", path, total_pages)

    for layer_fn in (_try_word_position, _try_hyperlink, _try_claude_api):
        result = layer_fn(path, total_pages)
        if result and result.start_page > 0:
            return result

    # Fallback: last third of document
    start = max(1, total_pages * 2 // 3)
    log.warning(
        "All TOC layers failed for '%s' - fallback pages %d-%d",
        path, start, total_pages,
    )
    return TOCResult(
        section_name="Consolidated Financial Statements (fallback)",
        start_page=start,
        end_page=total_pages,
        method="fallback",
    )
