"""
FastAPI web server — Financial Analysis AI

Routes
------
GET  /                             Serve the upload UI
POST /analyze                      Start a background analysis job
GET  /status/{job_id}              Poll job status and progress
GET  /download/{job_id}/report     Download the generated Word report
GET  /download/{job_id}/excel      Download the generated Excel workbook
POST /chat/{job_id}                Chatbot: answer questions about the report
POST /auto-detect                  Detect company name + fiscal years from an uploaded file
POST /upload-chunk                 Upload a file chunk (resumable multipart upload)
POST /upload-finalize/{upload_id}  Assemble chunks and return the combined file path
GET  /history                      List all completed analyses (from SQLite, with filters)
GET  /history/{job_id}             Full detail for a past analysis
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
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import (
    ANTHROPIC_API_KEY,
    ERROR_MSG_MAX_LENGTH,
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_SIZE_BYTES,
    MODEL_NAME,
)
from errors import AnalysisError, ExtractionError, ReportError, ValidationError
from web.db import delete_job, get_job_detail, init_db, list_jobs, upsert_job, upsert_report
from web.jobs import Job, create_job, get_job

# ── Bootstrap DB ──────────────────────────────────────────────────────────────
init_db()

# ── Constants ─────────────────────────────────────────────────────────────────
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
CHUNKS_DIR = Path(__file__).parent / "uploads" / "chunks"
CHUNKS_DIR.mkdir(exist_ok=True)

# Chunked upload: 1 GB per file (server assembles from chunks)
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

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Financial Analysis AI", version="2.0")
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
            data = json.loads(content.decode("utf-8"))
            company = data.get("company_name", "")
            years   = data.get("fiscal_years") or []
            # also harvest from statement arrays
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
            b64 = base64.b64encode(content).decode()
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
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

    # Count how many parts have arrived
    received = len(list(upload_dir.glob("*.part")))
    return JSONResponse({
        "upload_id":     upload_id,
        "chunk_index":   chunk_index,
        "received":      received,
        "total_chunks":  total_chunks,
        "complete":      received >= total_chunks,
    })


@app.post("/upload-finalize/{upload_id}")
async def upload_finalize(
    upload_id: str,
    filename:  str = Form(...),
    total_chunks: int = Form(...),
) -> JSONResponse:
    """
    Assemble all chunks for upload_id into a single file in UPLOADS_DIR.
    Returns the stable file path so /analyze can reference it directly.
    """
    upload_dir = CHUNKS_DIR / upload_id
    if not upload_dir.exists():
        raise HTTPException(404, f"No chunks found for upload_id={upload_id}")

    parts = [upload_dir / f"{i}.part" for i in range(total_chunks)]
    missing = [str(p) for p in parts if not p.exists()]
    if missing:
        raise HTTPException(400, f"Missing {len(missing)} chunk(s). Upload incomplete.")

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    out_path   = UPLOADS_DIR / f"{upload_id}_{safe_name}"

    with out_path.open("wb") as fout:
        for part in parts:
            fout.write(part.read_bytes())

    # Verify assembled size ≤ 1 GB
    if out_path.stat().st_size > MAX_UPLOAD_SIZE_CHUNKED:
        out_path.unlink(missing_ok=True)
        raise HTTPException(413, "Assembled file exceeds the 1 GB upload limit.")

    # Clean up chunk directory
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
async def analyze(
    background_tasks: BackgroundTasks,
    files:            List[UploadFile] = File(default=[]),
    pre_uploaded:     str              = Form(""),   # JSON array of paths from /upload-finalize
    company:          str              = Form(""),
    years:            str              = Form(""),
    currency:         str              = Form("INR"),
    unit:             str              = Form("Crores"),
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
            fp = Path(p)
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
                400, f"Unsupported file type: '{filename}'. Only .pdf or .json are accepted."
            )

        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            size_mb = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise HTTPException(400, f"'{filename}' exceeds the {size_mb} MB direct upload limit. Use chunked upload for larger files.")

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

    has_pdf = any(not j for j in is_json_flags)
    if has_pdf and not company.strip():
        raise HTTPException(400, "Company name is required for PDF uploads.")

    # Parse flexible year input
    fiscal_years: List[int] = []
    if years.strip():
        try:
            fiscal_years = parse_fiscal_years(years)
        except ValueError:
            raise HTTPException(
                400,
                "Years must be comma-separated integers or ranges, "
                "e.g. 2022,2023,2024 or 2016-2025 or 2016-2020,2022-2025"
            )

    # Persist job to DB immediately (status=queued)
    upsert_job(
        job_id=job.id,
        status="queued",
        company_name=company.strip(),
        currency=currency,
        unit=unit,
        fiscal_years=fiscal_years,
        created_at=job.created_at,
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
    )
    return JSONResponse({"job_id": job.id})


# ── Background Pipeline ───────────────────────────────────────────────────────

async def _run_pipeline(
    job:           Job,
    file_paths:    List[str],
    is_json_flags: List[bool],
    company:       str,
    fiscal_years:  List[int],
    currency:      str,
    unit:          str,
) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _run_pipeline_sync,
        job, file_paths, is_json_flags, company, fiscal_years, currency, unit,
    )


def _run_pipeline_sync(
    job:           Job,
    file_paths:    List[str],
    is_json_flags: List[bool],
    company:       str,
    fiscal_years:  List[int],
    currency:      str,
    unit:          str,
) -> None:
    job.status = "running"
    upsert_job(job_id=job.id, status="running", company_name=company,
               currency=currency, unit=unit, fiscal_years=fiscal_years,
               created_at=job.created_at)

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
        job.next_steps   = next_steps
        job.status       = "done"
        job.finished_at  = datetime.now().isoformat()

        # Persist to SQLite
        upsert_job(
            job_id=job.id, status="done",
            company_name=financial_data.company_name,
            currency=financial_data.currency,
            unit=financial_data.unit,
            fiscal_years=financial_data.sorted_years(),
            created_at=job.created_at,
            finished_at=job.finished_at,
        )
        upsert_report(
            job_id=job.id,
            report_path=report_path,
            excel_path=excel_path,
            commentary=commentary,
            next_steps=next_steps,
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
    except Exception as exc:  # Excel failure is non-fatal
        job.log("excel", f"Excel skipped: {str(exc)[:120]}", done=True)
        return None


def _step_report(job: Job, financial_data, commentary: Dict[str, str],
                 excel_path: Optional[str] = None) -> str:
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
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return JSONResponse(job.to_dict())


# ── Download Files ────────────────────────────────────────────────────────────

@app.get("/download/{job_id}/report")
def download_report(job_id: str) -> FileResponse:
    # Check in-memory store first, then DB
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
    limit:     int           = 50,
    offset:    int           = 0,
    status:    Optional[str] = None,
    company:   Optional[str] = None,
    year_from: Optional[int] = None,
    year_to:   Optional[int] = None,
) -> JSONResponse:
    """List analyses from the database, newest first. Supports filters."""
    return JSONResponse(list_jobs(
        limit=limit, offset=offset,
        status=status, company=company,
        year_from=year_from, year_to=year_to,
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


# ── Chatbot ───────────────────────────────────────────────────────────────────

class _ChatMessage(BaseModel):
    role:    str
    content: str


class _ChatRequest(BaseModel):
    message: str
    history: List[_ChatMessage] = []


@app.post("/chat/{job_id}")
def chat(job_id: str, body: _ChatRequest) -> JSONResponse:
    # Support chatting about historical (DB-stored) jobs too
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
