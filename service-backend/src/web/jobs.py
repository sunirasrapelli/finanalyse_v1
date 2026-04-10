"""
Thread-safe in-memory job store for background analysis tasks.

Each job tracks its full lifecycle:
  status:     queued → running → done | error
  progress:   list of step log entries streamed to the UI
  files:      output file paths once complete
  commentary: stored AI analysis sections (used by the chatbot)
"""
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Literal, Optional


class Job:
    __slots__ = (
        "id", "status", "progress", "files", "error",
        "next_steps", "commentary", "company_name",
        "created_at", "finished_at",
    )

    def __init__(self, job_id: str) -> None:
        self.id:           str                                           = job_id
        self.status:       Literal["queued", "running", "done", "error"] = "queued"
        self.progress:     List[Dict[str, object]]                       = []
        self.files:        Dict[str, str]                                = {}
        self.error:        Optional[str]                                 = None
        self.next_steps:   List[Dict[str, str]]                         = []
        self.commentary:   Dict[str, str]                               = {}
        self.company_name: str                                           = ""
        self.created_at:   str                                           = datetime.now().isoformat()
        self.finished_at:  Optional[str]                                 = None

    def log(self, step: str, message: str, *, done: bool = False) -> None:
        self.progress.append({"step": step, "message": message, "done": done})

    def to_dict(self) -> Dict[str, object]:
        return {
            "id":           self.id,
            "status":       self.status,
            "progress":     self.progress,
            "files":        {k: True for k in self.files},  # never expose server paths
            "error":        self.error,
            "next_steps":   self.next_steps,
            "company_name": self.company_name,
            "created_at":   self.created_at,
            "finished_at":  self.finished_at,
        }


# ── Thread-safe in-memory store ───────────────────────────────────────────────
_store:      Dict[str, Job] = {}
_store_lock: threading.Lock = threading.Lock()


def create_job() -> Job:
    job_id = str(uuid.uuid4())
    job    = Job(job_id)
    with _store_lock:
        _store[job_id] = job
    return job


def get_job(job_id: str) -> Optional[Job]:
    with _store_lock:
        return _store.get(job_id)


def all_jobs() -> List[Job]:
    """Return a snapshot of all jobs (newest first)."""
    with _store_lock:
        return sorted(_store.values(), key=lambda j: j.created_at, reverse=True)
