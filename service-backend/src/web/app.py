"""
FastAPI web server — Financial Analysis AI

Routes
------
GET  /                             Serve the upload UI
POST /analyze                      Start a background analysis job  (10/min rate limit)
GET  /status/{job_id}              Poll job status and progress (falls back to SQLite)
GET  /download/{job_id}/report     Download the generated Word report
GET  /download/{job_id}/excel      Download the generated Excel workbook
POST /chat/{job_id}                Chatbot: answer questions about the report
POST /compare                      Two-company comparison chat (requires auth)
POST /auto-detect                  Detect company name + fiscal years from an uploaded file
POST /upload-chunk                 Upload a file chunk (resumable multipart upload)
POST /upload-finalize/{upload_id}  Assemble chunks and return the combined file path
GET  /history                      List analyses (filtered by authenticated user when token present)
GET  /history/{job_id}             Full detail for a past analysis
DELETE /history/{job_id}           Delete a job record
GET  /auth/google                  Redirect to Google OAuth consent page
GET  /auth/callback                Google OAuth callback → issue JWT → redirect to frontend
GET  /auth/me                      Return current user info from JWT
GET  /health                       Health check
"""
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import anthropic
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import (
    ANTHROPIC_API_KEY,
    ERROR_MSG_MAX_LENGTH,
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_SIZE_BYTES,
    MODEL_NAME,
)
from errors import AnalysisError, ExtractionError, ReportError, ValidationError
from web.auth import (
    build_google_auth_url,
    create_jwt,
    exchange_code_for_user,
    get_current_user,
    get_optional_user,
    google_auth_enabled,
)
from web.db import (
    delete_job,
    get_job_detail,
    init_db,
    list_jobs,
    recover_stuck_jobs,
    upsert_job,
    upsert_report,
    upsert_user,
)
from web.jobs import Job, create_job, get_job

# ── Bootstrap DB ──────────────────────────────────────────────────────────────
init_db()
_recovered = recover_stuck_jobs()

# ── Constants ─────────────────────────────────────────────────────────────────
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
CHUNKS_DIR = Path(__file__).parent / "uploads" / "chunks"
CHUNKS_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_SIZE_CHUNKED = 1024 * 1024 * 1024  # 1 GB

COMMENTARY_SECTIONS: Dict[str, str] = {
    "executive_summary":      "Executive Summary",
    "revenue_analysis":       "Revenue Analysis",
    "profitability_analysis": "Profitability Analysis",
    "balance_sheet_analysis": "Balance Sheet Analysis",
    "cash_flow_analysis":     "Cash Flow Analysis",
    "key_risks":              "Key Risks",
    "key_strengths":          "Key Strengths",
}

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="FinAnalyse API", version="2.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
import os as _os

_ALLOWED_ORIGINS = [
    o.strip()
    for o in _os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8000,https://finanalyse-frontend-in.hack.nurixlabs.tech",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ──────────────────────────────────────────────────────────────
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "time": datetime.now().isoformat()}


# ── Serve UI ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/auth/google")
async def auth_google() -> RedirectResponse:
    """Redirect to Google OAuth consent page."""
    if not google_auth_enabled():
        raise HTTPException(503, "Google OAuth is not configured on this server")
    return RedirectResponse(build_google_auth_url())


@app.get("/auth/callback")
async def auth_callback(code: str = "", error: str = "") -> RedirectResponse:
    """
    Google redirects here after user grants consent.
    Exchanges the code, upserts the user, issues a JWT, and redirects to
    the frontend with  ?token=<jwt>  as a query parameter.
    """
    from web.auth import FRONTEND_URL

    if error:
        return RedirectResponse(f"{FRONTEND_URL}?auth_error={error}")
    if not code:
        return RedirectResponse(f"{FRONTEND_URL}?auth_error=missing_code")

    try:
        user_info = await exchange_code_for_user(code)
    except Exception as exc:
        return RedirectResponse(f"{FRONTEND_URL}?auth_error=google_api_failed")

    user_id = upsert_user(
        google_id=user_info["google_id"],
        email=user_info["email"],
        name=user_info["name"],
        picture=user_info["picture"],
    )

    token = create_jwt(user_id, user_info["email"])
    return RedirectResponse(f"{FRONTEND_URL}?token={token}")


@app.get("/auth/me")
async def auth_me(current_user: dict = Depends(get_current_user)) -> JSONResponse:
    """Return basic profile for the authenticated user."""
    from web.db import get_user_by_id
    user = get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(404, "User not found")
    # Never return internal DB ids; expose only safe fields
    return JSONResponse({
        "email":   user["email"],
        "name":    user["name"],
        "picture": user["picture"],
    })


# ── Year-range parser ─────────────────────────────────────────────────────────

def parse_fiscal_years(raw: str) -> List[int]:
    """
    Parse flexible year input into a sorted list of unique ints.

    Supported formats (mixed):
      "2022,2023,2024"       → [2022, 2023, 2024]
      "2016-2025"            → [2016..2025]
      "2016-2020,2022-2025"  → [2016..2020, 2022..2025]  (2021 excluded)
      "2018-2020, 2023"      → [2018, 2019, 2020, 2023]
    """
    years: List[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        range_match = re.match(r"^(\d{4})\s*-\s*(\d{4})$", token)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                raise ValueError(f"Invalid range: {token} (start > end)")
            years.extend(range(start, end + 1))
        else:
            years.append(int(token))
    if not years:
        raise ValueError("No valid years found")
    return sorted(set(years))


# ── Auto-detect endpoint ──────────────────────────────────────────────────────

@app.post("/auto-detect")
async def auto_detect(file: UploadFile = File(...)) -> JSONResponse:
    """
    Read the first uploaded file and return detected company_name + fiscal_years.
    For JSON files: parse directly.
    For PDF files: ask Claude to identify them from the first few pages.
    """
    filename = file.filename or ""
    content  = await file.read()

    if filename.endswith(".json"):
        try:
            data    = json.loads(content.decode("utf-8"))
            company = data.get("company_name", "")
            years   = data.get("fiscal_years") or []
            if not years:
                for key in ("income_statements", "balance_sheets", "cash_flow_statements"):
                    for stmt in data.get(key, []):
                        yr = stmt.get("fiscal_year")
                        if yr:
                            years.append(yr)
                years = sorted(set(years))
            return JSONResponse({"company_name": company, "fiscal_years": years})
        except Exception:
            return JSONResponse({"company_name": "", "fiscal_years": []})

    if filename.endswith(".pdf"):
        if not ANTHROPIC_API_KEY:
            return JSONResponse({"company_name": "", "fiscal_years": []})
        try:
            import base64
            import io
            from pypdf import PdfReader, PdfWriter
            # Truncate to first 5 pages to reduce tokens and latency
            try:
                reader = PdfReader(io.BytesIO(content))
                writer = PdfWriter()
                for i in range(min(5, len(reader.pages))):
                    writer.add_page(reader.pages[i])
                buf = io.BytesIO()
                writer.write(buf)
                content = buf.getvalue()
            except Exception:
                pass  # fall back to full PDF if truncation fails
            b64    = base64.b64encode(content).decode()
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp   = client.messages.create(
                model=MODEL_NAME,
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Look at this annual report cover page and table of contents. "
                                "Return ONLY a JSON object with:\n"
                                '{"company_name": "...", "fiscal_years": [2022, 2023, 2024]}\n'
                                "List all fiscal years present in the report."
                            ),
                        },
                    ],
                }],
            )
            text  = resp.content[0].text
            match = re.search(r'\{.*?"company_name".*?\}', text, re.DOTALL)
            if match:
                detected = json.loads(match.group())
                return JSONResponse({
                    "company_name": detected.get("company_name", ""),
                    "fiscal_years": detected.get("fiscal_years", []),
                })
        except Exception:
            pass
        return JSONResponse({"company_name": "", "fiscal_years": []})

    return JSONResponse({"company_name": "", "fiscal_years": []})


# ── Chunked / Resumable File Upload ──────────────────────────────────────────

@app.post("/upload-chunk")
async def upload_chunk(
    upload_id:    str        = Form(...),
    chunk_index:  int        = Form(...),
    total_chunks: int        = Form(...),
    filename:     str        = Form(...),
    chunk:        UploadFile = File(...),
) -> JSONResponse:
    """
    Receive one chunk of a multipart upload.
    The client slices the file into fixed-size pieces (e.g. 5 MB) and POSTs each
    one independently. Chunks are stored as  chunks/<upload_id>/<index>.part
    """
    if chunk_index < 0 or total_chunks < 1 or chunk_index >= total_chunks:
        raise HTTPException(400, "Invalid chunk_index or total_chunks")

    upload_dir = CHUNKS_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    part_path = upload_dir / f"{chunk_index}.part"
    data = await chunk.read()
    part_path.write_bytes(data)

    received = len(list(upload_dir.glob("*.part")))
    return JSONResponse({
        "upload_id":    upload_id,
        "chunk_index":  chunk_index,
        "received":     received,
        "total_chunks": total_chunks,
        "complete":     received >= total_chunks,
    })


@app.post("/upload-finalize/{upload_id}")
async def upload_finalize(
    upload_id:    str,
    filename:     str = Form(...),
    total_chunks: int = Form(...),
) -> JSONResponse:
    """
    Assemble all chunks for upload_id into a single file in UPLOADS_DIR.
    Returns the stable file path so /analyze can reference it directly.
    """
    upload_dir = CHUNKS_DIR / upload_id
    if not upload_dir.exists():
        raise HTTPException(404, f"No chunks found for upload_id={upload_id}")

    parts   = [upload_dir / f"{i}.part" for i in range(total_chunks)]
    missing = [str(p) for p in parts if not p.exists()]
    if missing:
        raise HTTPException(400, f"Missing {len(missing)} chunk(s). Upload incomplete.")

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    out_path  = UPLOADS_DIR / f"{upload_id}_{safe_name}"

    with out_path.open("wb") as fout:
        for part in parts:
            fout.write(part.read_bytes())

    if out_path.stat().st_size > MAX_UPLOAD_SIZE_CHUNKED:
        out_path.unlink(missing_ok=True)
        raise HTTPException(413, "Assembled file exceeds the 1 GB upload limit.")

    for part in parts:
        part.unlink(missing_ok=True)
    try:
        upload_dir.rmdir()
    except OSError:
        pass

    return JSONResponse({
        "upload_id":  upload_id,
        "filename":   safe_name,
        "path":       str(out_path),
        "size_bytes": out_path.stat().st_size,
    })


# ── Start Analysis Job ────────────────────────────────────────────────────────

@app.post("/analyze")
@limiter.limit("10/minute")
async def analyze(
    request:          Request,
    background_tasks: BackgroundTasks,
    files:            List[UploadFile] = File(default=[]),
    pre_uploaded:     str              = Form(""),
    company:          str              = Form(""),
    years:            str              = Form(""),
    currency:         str              = Form("INR"),
    unit:             str              = Form("Crores"),
    current_user:     Optional[dict]   = Depends(get_optional_user),
) -> JSONResponse:
    job           = create_job()
    saved_paths:   List[str]  = []
    is_json_flags: List[bool] = []

    # ── Handle pre-assembled chunked uploads ──────────────────────────
    if pre_uploaded.strip():
        try:
            paths = json.loads(pre_uploaded)
        except Exception:
            raise HTTPException(400, "pre_uploaded must be a JSON array of file paths")
        for p in paths:
            fp  = Path(p)
            if not fp.exists():
                raise HTTPException(400, f"Pre-uploaded file not found: {p}")
            ext = fp.suffix.lower()
            if ext not in (".json", ".pdf"):
                raise HTTPException(400, f"Unsupported file type: {fp.name}")
            saved_paths.append(str(fp))
            is_json_flags.append(ext == ".json")

    # ── Handle direct uploads (small files, ≤50 MB) ───────────────────
    for i, file in enumerate(files):
        filename = file.filename or ""
        is_json  = filename.endswith(".json")
        is_pdf   = filename.endswith(".pdf")

        if not (is_json or is_pdf):
            raise HTTPException(
                400,
                f"Unsupported file type: '{filename}'. Only .pdf or .json are accepted.",
            )

        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            size_mb = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise HTTPException(
                400,
                f"'{filename}' exceeds the {size_mb} MB direct upload limit. "
                "Use chunked upload for larger files.",
            )

        suffix     = ".json" if is_json else ".pdf"
        idx        = len(saved_paths)
        saved_path = UPLOADS_DIR / f"{job.id}_{idx}{suffix}"
        saved_path.write_bytes(content)

        saved_paths.append(str(saved_path))
        is_json_flags.append(is_json)

    if not saved_paths:
        raise HTTPException(400, "At least one file is required.")
    if len(saved_paths) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"Maximum {MAX_UPLOAD_FILES} files per request.")

    # company name is optional - pipeline will detect it from the PDF if not provided

    fiscal_years: List[int] = []
    if years.strip():
        try:
            fiscal_years = parse_fiscal_years(years)
        except ValueError:
            raise HTTPException(
                400,
                "Years must be comma-separated integers or ranges, "
                "e.g. 2022,2023,2024 or 2016-2025 or 2016-2020,2022-2025",
            )

    user_id = current_user["user_id"] if current_user else None

    upsert_job(
        job_id=job.id,
        status="queued",
        company_name=company.strip(),
        currency=currency,
        unit=unit,
        fiscal_years=fiscal_years,
        created_at=job.created_at,
        user_id=user_id,
    )

    background_tasks.add_task(
        _run_pipeline,
        job=job,
        file_paths=saved_paths,
        is_json_flags=is_json_flags,
        company=company.strip(),
        fiscal_years=fiscal_years,
        currency=currency,
        unit=unit,
        user_id=user_id,
    )
    return JSONResponse({"job_id": job.id})


# ── Metrics Helper ───────────────────────────────────────────────────────────

def _compute_metrics(fd) -> Dict:
    """
    Extract key financial metrics from FinancialData for the frontend stat cards.
    All values are in the same unit/currency as the report (Crores, Millions, etc.).
    Returns arrays per fiscal year so the frontend can draw sparklines.
    """
    years = fd.sorted_years()
    revenue: List[Optional[float]] = []
    gross_margin_pct: List[Optional[float]] = []
    fcf: List[Optional[float]] = []
    debt_equity: List[Optional[float]] = []

    for yr in years:
        is_ = fd.get_income_statement(yr)
        bs  = fd.get_balance_sheet(yr)
        cf  = fd.get_cash_flow(yr)

        # Revenue
        rev = is_.revenue if is_ and is_.revenue is not None else None
        revenue.append(rev)

        # Gross margin %
        gp = is_.gross_profit if is_ else None
        if gp is not None and rev:
            gross_margin_pct.append(round(gp / rev * 100, 1))
        else:
            gross_margin_pct.append(None)

        # Free cash flow = CFO + capex (capex stored as negative)
        if cf and cf.cash_from_operations is not None:
            cap = cf.capex if cf.capex is not None else 0.0
            fcf.append(round(cf.cash_from_operations + cap, 2))
        else:
            fcf.append(None)

        # Debt / Equity
        if bs and bs.total_equity and bs.total_equity != 0:
            debt = (bs.short_term_borrowings or 0.0) + (bs.long_term_debt or 0.0)
            debt_equity.append(round(debt / bs.total_equity, 1))
        else:
            debt_equity.append(None)

    return {
        "years":            years,
        "revenue":          revenue,
        "gross_margin_pct": gross_margin_pct,
        "fcf":              fcf,
        "debt_equity":      debt_equity,
    }


# ── Background Pipeline ───────────────────────────────────────────────────────

async def _run_pipeline(
    job:           Job,
    file_paths:    List[str],
    is_json_flags: List[bool],
    company:       str,
    fiscal_years:  List[int],
    currency:      str,
    unit:          str,
    user_id:       Optional[str] = None,
) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _run_pipeline_sync,
        job, file_paths, is_json_flags, company, fiscal_years, currency, unit, user_id,
    )


def _run_pipeline_sync(
    job:           Job,
    file_paths:    List[str],
    is_json_flags: List[bool],
    company:       str,
    fiscal_years:  List[int],
    currency:      str,
    unit:          str,
    user_id:       Optional[str] = None,
) -> None:
    job.status = "running"
    upsert_job(
        job_id=job.id, status="running", company_name=company,
        currency=currency, unit=unit, fiscal_years=fiscal_years,
        created_at=job.created_at, user_id=user_id,
    )

    try:
        financial_data = _step_extract(
            job, file_paths, is_json_flags, company, fiscal_years, currency, unit
        )
        commentary  = _step_commentary(job, financial_data)
        excel_path  = _step_excel(job, financial_data)
        report_path = _step_report(job, financial_data, commentary, excel_path)
        next_steps  = _step_next_steps(job, financial_data, commentary)

        job.files        = {"report": report_path, "excel": excel_path}
        job.commentary   = commentary
        job.company_name = financial_data.company_name
        job.currency     = financial_data.currency
        job.unit         = financial_data.unit
        job.fiscal_years = financial_data.sorted_years()
        job.next_steps   = next_steps
        job.metrics      = _compute_metrics(financial_data)
        job.status       = "done"
        job.finished_at  = datetime.now().isoformat()

        upsert_job(
            job_id=job.id, status="done",
            company_name=financial_data.company_name,
            currency=financial_data.currency,
            unit=financial_data.unit,
            fiscal_years=financial_data.sorted_years(),
            created_at=job.created_at,
            finished_at=job.finished_at,
            user_id=user_id,
        )
        upsert_report(
            job_id=job.id,
            report_path=report_path,
            excel_path=excel_path,
            commentary=commentary,
            next_steps=next_steps,
            metrics=job.metrics,
        )

    except (ExtractionError, ValidationError, AnalysisError, ReportError) as exc:
        _fail_job(job, str(exc))
    except Exception as exc:
        _fail_job(job, _sanitise_error(str(exc)))
    finally:
        _cleanup_uploads(file_paths)


def _step_extract(
    job:           Job,
    file_paths:    List[str],
    is_json_flags: List[bool],
    company:       str,
    fiscal_years:  List[int],
    currency:      str,
    unit:          str,
):
    from agents.extractor import (
        extract_from_json,
        extract_from_pdf,
        merge_financial_data,
        validate_relevance,
    )

    n = len(file_paths)
    job.log("extract", f"Extracting from {n} file(s)…")

    all_data = []
    for i, (fp, is_json) in enumerate(zip(file_paths, is_json_flags)):
        job.log("extract", f"Processing file {i + 1}/{n}…")
        if is_json:
            fd = extract_from_json(fp)
        else:
            fd = extract_from_pdf(
                path=fp,
                company_name=company,
                fiscal_years=fiscal_years or list(range(2022, 2025)),
                currency=currency,
                unit=unit,
            )
        validate_relevance(fd, Path(fp).name)
        all_data.append(fd)

    from models.company_data import FinancialData
    financial_data: FinancialData = merge_financial_data(all_data)
    job.log(
        "extract",
        f"Extracted {len(financial_data.sorted_years())} year(s) for "
        f"{financial_data.company_name} "
        f"(confidence: {financial_data.metadata.overall_confidence:.0%})",
        done=True,
    )
    return financial_data


def _step_commentary(job: Job, financial_data) -> Dict[str, str]:
    from agents.analyzer import generate_commentary
    job.log("commentary", "Generating AI commentary…")
    commentary = generate_commentary(financial_data)
    job.log("commentary", "AI commentary generated ✓", done=True)
    return commentary


def _step_excel(job: Job, financial_data) -> Optional[str]:
    """Build the Excel workbook. Returns path or None on failure (non-fatal)."""
    try:
        from agents.excel_builder import build_workbook
        job.log("excel", "Building Excel financial model…")
        excel_path: str = build_workbook(financial_data)
        job.log("excel", f"Excel model built — {Path(excel_path).name}", done=True)
        return excel_path
    except Exception as exc:
        job.log("excel", f"Excel skipped: {str(exc)[:120]}", done=True)
        return None


def _step_report(
    job: Job,
    financial_data,
    commentary: Dict[str, str],
    excel_path: Optional[str] = None,
) -> str:
    from agents.report_generator import generate_report
    job.log("report", "Building Word report…")
    report_path: str = generate_report(financial_data, commentary, excel_path=excel_path)
    job.log("report", f"Report built — {Path(report_path).name}", done=True)
    return report_path


def _step_next_steps(
    job: Job, financial_data, commentary: Dict[str, str]
) -> List[Dict[str, str]]:
    from agents.analyzer import generate_next_steps
    job.log("next_steps", "Generating AI next steps…")
    next_steps = generate_next_steps(financial_data, commentary)
    job.log("next_steps", f"{len(next_steps)} next steps generated ✓", done=True)
    return next_steps


# ── Pipeline helpers ──────────────────────────────────────────────────────────

def _fail_job(job: Job, message: str) -> None:
    job.log("error", message)
    job.status      = "error"
    job.error       = message
    job.finished_at = datetime.now().isoformat()
    upsert_job(
        job_id=job.id, status="error",
        company_name=job.company_name,
        error=message,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def _sanitise_error(raw: str) -> str:
    clean = re.sub(r"<[^>]+>", "", raw).strip()
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:ERROR_MSG_MAX_LENGTH] or "An unexpected error occurred."


def _cleanup_uploads(file_paths: List[str]) -> None:
    for fp in file_paths:
        try:
            Path(fp).unlink(missing_ok=True)
        except OSError:
            pass


# ── Poll Status ───────────────────────────────────────────────────────────────

@app.get("/status/{job_id}")
def status(job_id: str) -> JSONResponse:
    """
    Return job status. Checks in-memory store first; falls back to SQLite
    so that completed jobs survive pod restarts.
    """
    job = get_job(job_id)
    if job:
        return JSONResponse(job.to_dict())

    # Pod-restart fallback: reconstruct a minimal status response from SQLite
    detail = get_job_detail(job_id)
    if not detail:
        raise HTTPException(404, "Job not found")

    return JSONResponse({
        "id":           detail["id"],
        "status":       detail["status"],
        "progress":     [],   # ephemeral; not persisted
        "files": {
            "report": bool(detail.get("report_path")),
            "excel":  bool(detail.get("excel_path")),
        },
        "error":        detail.get("error"),
        "next_steps":   detail.get("next_steps") or [],
        "company_name": detail.get("company_name", ""),
        "currency":     detail.get("currency", ""),
        "unit":         detail.get("unit", ""),
        "fiscal_years": detail.get("fiscal_years") or [],
        "created_at":   detail.get("created_at"),
        "finished_at":  detail.get("finished_at"),
        "metrics":      detail.get("metrics"),  # persisted in reports table
    })


# ── Download Files ────────────────────────────────────────────────────────────

@app.get("/download/{job_id}/report")
def download_report(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job and job.status == "done":
        path = job.files.get("report")
    else:
        detail = get_job_detail(job_id)
        if not detail or detail.get("status") != "done":
            raise HTTPException(404, "File not ready")
        path = detail.get("report_path")

    if not path or not Path(path).exists():
        raise HTTPException(404, "Report file not found")
    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        filename=Path(path).name,
    )


@app.get("/download/{job_id}/excel")
def download_excel(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job and job.status == "done":
        path = job.files.get("excel")
    else:
        detail = get_job_detail(job_id)
        if not detail or detail.get("status") != "done":
            raise HTTPException(404, "File not ready")
        path = detail.get("excel_path")

    if not path or not Path(path).exists():
        raise HTTPException(404, "Excel file not found")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(path).name,
    )


# ── History endpoints ─────────────────────────────────────────────────────────

@app.get("/history")
def history(
    request:      Request,
    limit:        int            = 50,
    offset:       int            = 0,
    status:       Optional[str]  = None,
    company:      Optional[str]  = None,
    year_from:    Optional[int]  = None,
    year_to:      Optional[int]  = None,
    current_user: Optional[dict] = Depends(get_optional_user),
) -> JSONResponse:
    """
    List analyses newest-first with optional filters.
    When an authenticated user makes the request, returns only their jobs.
    Unauthenticated requests return all jobs (demo mode).
    """
    user_id = current_user["user_id"] if current_user else None
    return JSONResponse(list_jobs(
        limit=limit, offset=offset,
        status=status, company=company,
        year_from=year_from, year_to=year_to,
        user_id=user_id,
    ))


@app.get("/history/{job_id}")
def history_detail(job_id: str) -> JSONResponse:
    """Full detail for a single past analysis."""
    detail = get_job_detail(job_id)
    if not detail:
        raise HTTPException(404, "Job not found")
    return JSONResponse(detail)


@app.delete("/history/{job_id}")
def delete_report(job_id: str) -> JSONResponse:
    deleted = delete_job(job_id)
    if not deleted:
        raise HTTPException(404, "Job not found")
    return JSONResponse({"deleted": True})


# ── Single-company Chatbot ────────────────────────────────────────────────────

class _ChatMessage(BaseModel):
    role:    str
    content: str


class _ChatRequest(BaseModel):
    message: str
    history: List[_ChatMessage] = []


@app.post("/chat/{job_id}")
def chat(job_id: str, body: _ChatRequest) -> JSONResponse:
    """Answer questions grounded in the AI commentary for a single completed job."""
    job = get_job(job_id)
    if job and job.status == "done":
        commentary   = job.commentary
        company_name = job.company_name
    else:
        detail = get_job_detail(job_id)
        if not detail or detail.get("status") != "done":
            raise HTTPException(404, "Analysis not found or not yet complete")
        commentary   = detail.get("commentary") or {}
        company_name = detail.get("company_name", "")

    if not commentary:
        raise HTTPException(400, "No analysis context is available for this job")
    if not ANTHROPIC_API_KEY:
        raise HTTPException(503, "ANTHROPIC_API_KEY is not configured on this server")

    context = "\n\n".join(
        f"### {label}\n{commentary[key]}"
        for key, label in COMMENTARY_SECTIONS.items()
        if key in commentary and commentary[key]
    )

    system_prompt = (
        f"You are a financial analyst assistant. You have just completed an "
        f"AI-generated analysis of {company_name or 'this company'}. "
        f"Answer the user's questions using only the analysis below. "
        f"Be concise and precise. Reference specific figures or sections where relevant.\n\n"
        f"--- ANALYSIS REPORT ---\n{context}\n--- END OF REPORT ---"
    )

    messages = [{"role": m.role, "content": m.content} for m in body.history]
    messages.append({"role": "user", "content": body.message})

    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )
    return JSONResponse({"reply": response.content[0].text})


# ── Two-company Comparison Chat ───────────────────────────────────────────────

class _CompareRequest(BaseModel):
    """
    /compare body:
      job_ids — exactly 2 completed job IDs to compare
      message — user's question about the two companies
      history — conversation history (role/content pairs)
    """
    job_ids: List[str]
    message: str
    history: List[_ChatMessage] = []


@app.post("/compare")
def compare(body: _CompareRequest) -> JSONResponse:
    """
    Answer questions that compare two completed analyses side-by-side.

    Builds a combined context from both jobs' commentary (~6 K tokens total)
    and sends it to Claude as the system prompt. No RAG — direct injection is
    sufficient for 2 companies at this scale.
    """
    if len(body.job_ids) != 2:
        raise HTTPException(400, "Exactly 2 job_ids are required for comparison")
    if not ANTHROPIC_API_KEY:
        raise HTTPException(503, "ANTHROPIC_API_KEY is not configured on this server")

    analyses = []
    for job_id in body.job_ids:
        job = get_job(job_id)
        if job and job.status == "done":
            commentary   = job.commentary
            company_name = job.company_name
        else:
            detail = get_job_detail(job_id)
            if not detail or detail.get("status") != "done":
                raise HTTPException(404, f"Analysis {job_id!r} not found or not yet complete")
            commentary   = detail.get("commentary") or {}
            company_name = detail.get("company_name", "Unknown")

        if not commentary:
            raise HTTPException(400, f"No analysis context available for job {job_id!r}")

        context = "\n\n".join(
            f"#### {label}\n{commentary[key]}"
            for key, label in COMMENTARY_SECTIONS.items()
            if key in commentary and commentary[key]
        )
        analyses.append({"name": company_name, "context": context})

    system_prompt = (
        "You are a senior equity analyst. You have two AI-generated financial analyses "
        "below. Answer the user's comparative questions using only the analyses provided. "
        "Be concise, precise, and cite specific figures where relevant.\n\n"
        f"=== COMPANY 1: {analyses[0]['name']} ===\n"
        f"{analyses[0]['context']}\n\n"
        f"=== COMPANY 2: {analyses[1]['name']} ===\n"
        f"{analyses[1]['context']}\n\n"
        "=== END OF ANALYSES ==="
    )

    messages = [{"role": m.role, "content": m.content} for m in body.history]
    messages.append({"role": "user", "content": body.message})

    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )
    return JSONResponse({
        "reply":    response.content[0].text,
        "companies": [a["name"] for a in analyses],
    })
