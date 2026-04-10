"""
SQLite persistence layer for FinAnalyse AI.

Schema
------
jobs       — one row per analysis job (metadata + status)
reports    — one row per completed report (file path, commentary JSON)
next_steps — one row per next-step item linked to a job

All timestamps stored as ISO-8601 strings in UTC.
"""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent.parent / "outputs" / "finanalyse.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_local = threading.local()   # per-thread connection


def _conn() -> sqlite3.Connection:
    """Return (or create) the thread-local SQLite connection."""
    if not getattr(_local, "con", None):
        con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        _local.con = con
    return _local.con


def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    con = _conn()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id           TEXT PRIMARY KEY,
            status       TEXT NOT NULL DEFAULT 'queued',
            company_name TEXT,
            currency     TEXT,
            unit         TEXT,
            fiscal_years TEXT,          -- JSON array of ints
            error        TEXT,
            created_at   TEXT NOT NULL,
            finished_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS reports (
            job_id       TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
            report_path  TEXT,
            excel_path   TEXT,
            commentary   TEXT,          -- JSON object (7 sections)
            next_steps   TEXT           -- JSON array
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
    """)
    # Migration: add excel_path column if it doesn't exist (for pre-existing DBs)
    try:
        con.execute("ALTER TABLE reports ADD COLUMN excel_path TEXT")
        con.commit()
    except Exception:
        pass  # Column already exists
    con.commit()


# ── Write helpers ─────────────────────────────────────────────────────────────

def upsert_job(
    job_id:      str,
    status:      str,
    company_name: str = "",
    currency:    str = "INR",
    unit:        str = "Crores",
    fiscal_years: Optional[List[int]] = None,
    error:       Optional[str] = None,
    created_at:  Optional[str] = None,
    finished_at: Optional[str] = None,
) -> None:
    con = _conn()
    con.execute("""
        INSERT INTO jobs (id, status, company_name, currency, unit,
                          fiscal_years, error, created_at, finished_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status       = excluded.status,
            company_name = excluded.company_name,
            currency     = excluded.currency,
            unit         = excluded.unit,
            fiscal_years = excluded.fiscal_years,
            error        = excluded.error,
            finished_at  = excluded.finished_at
    """, (
        job_id, status, company_name, currency, unit,
        json.dumps(fiscal_years or []),
        error,
        created_at or datetime.utcnow().isoformat(),
        finished_at,
    ))
    con.commit()


def upsert_report(
    job_id:      str,
    report_path: str,
    commentary:  Dict[str, str],
    next_steps:  List[Dict[str, str]],
    excel_path:  Optional[str] = None,
) -> None:
    con = _conn()
    con.execute("""
        INSERT INTO reports (job_id, report_path, excel_path, commentary, next_steps)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            report_path = excluded.report_path,
            excel_path  = excluded.excel_path,
            commentary  = excluded.commentary,
            next_steps  = excluded.next_steps
    """, (
        job_id,
        report_path,
        excel_path,
        json.dumps(commentary),
        json.dumps(next_steps),
    ))
    con.commit()


# ── Read helpers ──────────────────────────────────────────────────────────────

def list_jobs(
    limit:        int = 50,
    offset:       int = 0,
    status:       Optional[str] = None,
    company:      Optional[str] = None,
    year_from:    Optional[int] = None,
    year_to:      Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return recent jobs newest-first, joined with report metadata. Supports filters."""
    con = _conn()
    where_clauses = []
    params: List[Any] = []

    if status:
        where_clauses.append("j.status = ?")
        params.append(status)
    if company:
        where_clauses.append("LOWER(j.company_name) LIKE ?")
        params.append(f"%{company.lower()}%")
    if year_from is not None:
        # fiscal_years is a JSON array; use a simple string match heuristic
        where_clauses.append("j.fiscal_years LIKE ?")
        params.append(f"%{year_from}%")
    if year_to is not None:
        where_clauses.append("j.fiscal_years LIKE ?")
        params.append(f"%{year_to}%")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    rows = con.execute(f"""
        SELECT j.id, j.status, j.company_name, j.currency, j.unit,
               j.fiscal_years, j.error, j.created_at, j.finished_at,
               r.report_path, r.excel_path
        FROM jobs j
        LEFT JOIN reports r ON r.job_id = j.id
        {where_sql}
        ORDER BY j.created_at DESC
        LIMIT ? OFFSET ?
    """, (*params, limit, offset)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job_detail(job_id: str) -> Optional[Dict[str, Any]]:
    """Return full job + report detail for the history view."""
    con = _conn()
    row = con.execute("""
        SELECT j.id, j.status, j.company_name, j.currency, j.unit,
               j.fiscal_years, j.error, j.created_at, j.finished_at,
               r.report_path, r.excel_path, r.commentary, r.next_steps
        FROM jobs j
        LEFT JOIN reports r ON r.job_id = j.id
        WHERE j.id = ?
    """, (job_id,)).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    if d.get("commentary") and isinstance(d["commentary"], str):
        d["commentary"]  = json.loads(d["commentary"])
    if d.get("next_steps") and isinstance(d["next_steps"], str):
        d["next_steps"]  = json.loads(d["next_steps"])
    return d


def delete_job(job_id: str) -> bool:
    """Delete a job by id. CASCADE removes the linked report row. Returns True if deleted."""
    con = _conn()
    cursor = con.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    con.commit()
    return cursor.rowcount > 0


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("fiscal_years") and isinstance(d["fiscal_years"], str):
        try:
            d["fiscal_years"] = json.loads(d["fiscal_years"])
        except Exception:
            pass
    return d
