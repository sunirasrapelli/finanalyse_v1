"""
PDF utility functions: load, encode, page-count, and page-range extraction.
"""
import base64
from pathlib import Path
from typing import Optional

from pypdf import PdfReader, PdfWriter


def load_pdf_as_base64(path: str) -> str:
    """Read a PDF file and return its base64-encoded content."""
    data = Path(path).read_bytes()
    return base64.standard_b64encode(data).decode("utf-8")


def get_pdf_page_count(path: str) -> int:
    """Return the number of pages in a PDF."""
    reader = PdfReader(path)
    return len(reader.pages)


def extract_page_range_as_base64(
    path: str,
    start_page: int,
    end_page: int,
    output_path: Optional[str] = None,
) -> str:
    """
    Extract pages [start_page, end_page] (1-based, inclusive) from a PDF
    and return the subset as a base64-encoded string.
    Optionally save to output_path for debugging.
    """
    reader = PdfReader(path)
    writer = PdfWriter()

    # Clamp to actual page range
    total = len(reader.pages)
    start_idx = max(0, start_page - 1)
    end_idx = min(total - 1, end_page - 1)

    for i in range(start_idx, end_idx + 1):
        writer.add_page(reader.pages[i])

    import io
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    if output_path:
        Path(output_path).write_bytes(pdf_bytes)

    return base64.standard_b64encode(pdf_bytes).decode("utf-8")


def validate_pdf(path: str) -> bool:
    """Return True if the file exists and is a readable PDF."""
    p = Path(path)
    if not p.exists() or p.suffix.lower() != ".pdf":
        return False
    try:
        PdfReader(path)
        return True
    except Exception:
        return False
