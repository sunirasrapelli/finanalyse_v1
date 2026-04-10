"""
SQLite persistence layer for FinAnalyse AI.

Schema
------
users      — Google OAuth users (one row per Google account)
jobs       — one row per analysis job (metadata + status + optional user FK)
reports    — one row per completed report (file paths, commentary JSON, next steps)

All timestamps stored as ISO-8601 strings in UTC.
"""
import json
import sqlite3
import threading
import uuid
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
        CREATE TABLE IF NOT EXISTS users (
            id         TEXT PRIMARY KEY,
            google_id  TEXT UNIQUE NOT NULL,
            email      TEXT NOT NULL,
            name       TEXT,
            picture    TEXT,
            created_at TEXT NOT NULL,
            last_login TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id           TEXT PRIMARY KEY,
            status       TEXT NOT NULL DEFAULT 'queued',
            company_name TEXT,
            currency     TEXT,
            unit         TEXT,
            fiscal_years TEXT,          -- JSON array of ints
            error        TEXT,
            created_at   TEXT NOT NULL,
            finished_at  TEXT,
            user_id      TEXT REFERENCES users(id)
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
        CREATE INDEX IF NOT EXISTS idx_jobs_user    ON jobs(user_id);
    """)

    # ── Migrations for pre-existing databases ────────────────────────────────
    _safe_alter("ALTER TABLE reports ADD COLUMN excel_path TEXT")
    _safe_alter("ALTER TABLE jobs    ADD COLUMN user_id TEXT REFERENCES users(id)")
    _safe_alter("ALTER TABLE reports ADD COLUMN metrics TEXT")

    con.commit()


def _safe_alter(sql: str) -> None:
    """Run an ALTER TABLE statement, ignoring errors (column already exists)."""
    try:
        _conn().execute(sql)
        _conn().commit()
    except Exception:
        pass


def recover_stuck_jobs() -> int:
    """
    On startup, mark any jobs still in 'queued' or 'running' state as 'error'.
    These are jobs whose background task was lost when the process restarted.
    Returns the number of jobs recovered.
    """
    con = _conn()
    cursor = con.execute(
        """
        UPDATE jobs
        SET    status      = 'error',
               error       = 'Server restarted; analysis was interrupted',
               finished_at = ?
        WHERE  status IN ('queued', 'running')
        """,
        (datetime.utcnow().isoformat(),),
    )
    con.commit()
    return cursor.rowcount


# ── User helpers ──────────────────────────────────────────────────────────────

def upsert_user(
    google_id: str,
    email:     str,
    name:      str = "",
    picture:   str = "",
) -> str:
    """
    Insert or update a user row keyed by google_id.
    Returns the internal user UUID (creates one on first login).
    """
    con = _conn()
    now = datetime.utcnow().isoformat()

    existing = con.execute(
        "SELECT id FROM users WHERE google_id = ?", (google_id,)
    ).fetchone()

    if existing:
        user_id = existing["id"]
        con.execute(
            "UPDATE users SET email=?, name=?, picture=?, last_login=? WHERE id=?",
            (email, name, picture, now, user_id),
        )
    else:
        user_id = str(uuid.uuid4())
        con.execute(
            "INSERT INTO users (id, google_id, email, name, picture, created_at, last_login) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, google_id, email, name, picture, now, now),
        )

    con.commit()
    return user_id


def get_user_by_google_id(google_id: str) -> Optional[Dict[str, Any]]:
    row = _conn().execute(
        "SELECT * FROM users WHERE google_id = ?", (google_id,)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    row = _conn().execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


# ── Job write helpers ─────────────────────────────────────────────────────────

def upsert_job(
    job_id:       str,
    status:       str,
    company_name: str = "",
    currency:     str = "INR",
    unit:         str = "Crores",
    fiscal_years: Optional[List[int]] = None,
    error:        Optional[str] = None,
    created_at:   Optional[str] = None,
    finished_at:  Optional[str] = None,
    user_id:      Optional[str] = None,
) -> None:
    con = _conn()
    con.execute(
        """
        INSERT INTO jobs (id, status, company_name, currency, unit,
                          fiscal_years, error, created_at, finished_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status       = excluded.status,
            company_name = CASE WHEN excluded.company_name != '' THEN excluded.company_name ELSE jobs.company_name END,
            currency     = CASE WHEN excluded.currency     != '' THEN excluded.currency     ELSE jobs.currency     END,
            unit         = CASE WHEN excluded.unit         != '' THEN excluded.unit         ELSE jobs.unit         END,
            fiscal_years = CASE WHEN excluded.fiscal_years != '[]' THEN excluded.fiscal_years ELSE jobs.fiscal_years END,
            error        = excluded.error,
            finished_at  = excluded.finished_at,
            user_id      = COALESCE(excluded.user_id, jobs.user_id)
        """,
        (
            job_id, status, company_name, currency, unit,
            json.dumps(fiscal_years or []),
            error,
            created_at or datetime.utcnow().isoformat(),
            finished_at,
            user_id,
        ),
    )
    con.commit()


def upsert_report(
    job_id:      str,
    report_path: str,
    commentary:  Dict[str, str],
    next_steps:  List[Dict[str, str]],
    excel_path:  Optional[str] = None,
    metrics:     Optional[Dict] = None,
) -> None:
    con = _conn()
    con.execute(
        """
        INSERT INTO reports (job_id, report_path, excel_path, commentary, next_steps, metrics)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            report_path = excluded.report_path,
            excel_path  = excluded.excel_path,
            commentary  = excluded.commentary,
            next_steps  = excluded.next_steps,
            metrics     = excluded.metrics
        """,
        (
            job_id,
            report_path,
            excel_path,
            json.dumps(commentary),
            json.dumps(next_steps),
            json.dumps(metrics) if metrics is not None else None,
        ),
    )
    con.commit()


# ── Job read helpers ──────────────────────────────────────────────────────────

def list_jobs(
    limit:     int = 50,
    offset:    int = 0,
    status:    Optional[str] = None,
    company:   Optional[str] = None,
    year_from: Optional[int] = None,
    year_to:   Optional[int] = None,
    user_id:   Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return recent jobs newest-first, joined with report metadata. Supports filters."""
    con = _conn()
    where_clauses: List[str] = []
    params: List[Any] = []

    if status:
        where_clauses.append("j.status = ?")
        params.append(status)
    if company:
        where_clauses.append("LOWER(j.company_name) LIKE ?")
        params.append(f"%{company.lower()}%")
    if year_from is not None:
        where_clauses.append("j.fiscal_years LIKE ?")
        params.append(f"%{year_from}%")
    if year_to is not None:
        where_clauses.append("j.fiscal_years LIKE ?")
        params.append(f"%{year_to}%")
    if user_id is not None:
        # Show the user's own jobs AND any unclaimed (anonymous) jobs so that
        # analyses run before login are still visible after authenticating.
        where_clauses.append("(j.user_id = ? OR j.user_id IS NULL)")
        params.append(user_id)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    rows = con.execute(
        f"""
        SELECT j.id, j.id AS job_id, j.status, j.company_name, j.currency, j.unit,
               j.fiscal_years, j.error, j.created_at, j.finished_at, j.user_id,
               r.report_path, r.excel_path
        FROM   jobs j
        LEFT JOIN reports r ON r.job_id = j.id
        {where_sql}
        ORDER BY j.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job_detail(job_id: str) -> Optional[Dict[str, Any]]:
    """Return full job + report detail including commentary, next_steps, and metrics."""
    con = _conn()
    row = con.execute(
        """
        SELECT j.id, j.id AS job_id, j.status, j.company_name, j.currency, j.unit,
               j.fiscal_years, j.error, j.created_at, j.finished_at, j.user_id,
               r.report_path, r.excel_path, r.commentary, r.next_steps, r.metrics
        FROM   jobs j
        LEFT JOIN reports r ON r.job_id = j.id
        WHERE  j.id = ?
        """,
        (job_id,),
    ).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    if d.get("commentary") and isinstance(d["commentary"], str):
        d["commentary"] = json.loads(d["commentary"])
    if d.get("next_steps") and isinstance(d["next_steps"], str):
        d["next_steps"] = json.loads(d["next_steps"])
    if d.get("metrics") and isinstance(d["metrics"], str):
        d["metrics"] = json.loads(d["metrics"])
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
