"""
Multi-Agent Financial Statement Extractor

Architecture
------------
  Dispatcher Agent (main thread)
    - Processes PDFs one by one
    - Runs TOC Navigator to find Consolidated FS page range
    - Assigns tasks round-robin across 3 worker queues

  Extraction Worker 1/2/3 (daemon threads)
    - Each has its own queue (mailbox model - preserves round-robin order)
    - Blocks on queue.get(), processes task, loops
    - Calls extract_from_pdf_range (pdfplumber + 3 parallel Claude sub-agents)

Round-robin cycle
-----------------
  PDF 1 -> Worker-1,  PDF 2 -> Worker-2,  PDF 3 -> Worker-3
  PDF 4 -> Worker-1,  PDF 5 -> Worker-2,  PDF 6 -> Worker-3  ...

If a worker is still busy when the next task is assigned to it, the task
waits in that worker's queue. Workers are never reassigned out of cycle.

Public API
----------
  run_multi_agent_extraction(pdf_inputs) -> MultiAgentResult
  print_status_table(result)
"""
import os
import queue
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.toc_navigator import TOCResult, navigate_to_consolidated_fs
from utils.logger import get_logger

log = get_logger(__name__)

NUM_WORKERS = 3

# ── Task dataclass ─────────────────────────────────────────────────────────────

@dataclass
class ExtractionTask:
    task_id:          str
    pdf_path:         str
    pdf_name:         str
    section_name:     str
    start_page:       int
    end_page:         int
    assigned_worker:  int           # 1-based
    state:            str = "queued"  # queued | in_progress | completed | failed
    company_name:     str = ""
    fiscal_years:     List[int] = field(default_factory=list)
    currency:         str = "INR"
    unit:             str = "Crores"
    toc_method:       str = ""
    result:           Any = None    # FinancialData on success
    error:            Optional[str] = None
    created_at:       float = field(default_factory=time.time)
    started_at:       Optional[float] = None
    completed_at:     Optional[float] = None

    # ── Status helpers ──────────────────────────────────────────────────────────

    @property
    def duration_s(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return round(self.completed_at - self.started_at, 1)
        return None

    def as_dict(self) -> dict:
        return {
            "task_id":          self.task_id,
            "pdf_name":         self.pdf_name,
            "section_name":     self.section_name,
            "start_page":       self.start_page,
            "end_page":         self.end_page,
            "pages":            self.end_page - self.start_page + 1 if self.start_page else 0,
            "assigned_worker":  f"Worker-{self.assigned_worker}",
            "state":            self.state,
            "toc_method":       self.toc_method,
            "duration_s":       self.duration_s,
            "error":            self.error,
        }


# ── Thread-safe registry ───────────────────────────────────────────────────────

class TaskRegistry:
    """Thread-safe store tracking all ExtractionTask objects."""

    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._tasks: Dict[str, ExtractionTask] = {}

    def register(self, task: ExtractionTask) -> None:
        with self._lock:
            self._tasks[task.task_id] = task

    def update(self, task_id: str, **kwargs) -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                for k, v in kwargs.items():
                    setattr(t, k, v)

    def all_tasks(self) -> List[ExtractionTask]:
        with self._lock:
            return list(self._tasks.values())

    def summary(self) -> dict:
        tasks = self.all_tasks()
        counts: Dict[str, int] = {}
        for t in tasks:
            counts[t.state] = counts.get(t.state, 0) + 1
        return {
            "total":       len(tasks),
            "queued":      counts.get("queued", 0),
            "in_progress": counts.get("in_progress", 0),
            "completed":   counts.get("completed", 0),
            "failed":      counts.get("failed", 0),
        }


# ── Worker thread ──────────────────────────────────────────────────────────────

def _worker_loop(
    worker_id:   int,
    work_queue:  "queue.Queue[Optional[ExtractionTask]]",
    registry:    TaskRegistry,
) -> None:
    """
    Worker thread: pull tasks from the dedicated queue, extract, mark done.
    A None sentinel signals shutdown.
    """
    log.info("[Worker-%d] started and waiting for tasks.", worker_id)

    while True:
        task: Optional[ExtractionTask] = work_queue.get()

        if task is None:                # shutdown sentinel
            log.info("[Worker-%d] shutting down.", worker_id)
            work_queue.task_done()
            break

        log.info(
            "[Worker-%d] starting '%s' pages %d-%d (toc_method=%s)",
            worker_id, task.pdf_name, task.start_page, task.end_page, task.toc_method,
        )
        registry.update(task.task_id, state="in_progress", started_at=time.time())

        try:
            result = _extract_range(task)
            registry.update(
                task.task_id,
                state="completed",
                result=result,
                completed_at=time.time(),
            )
            log.info("[Worker-%d] completed '%s'.", worker_id, task.pdf_name)

        except Exception as exc:
            registry.update(
                task.task_id,
                state="failed",
                error=str(exc),
                completed_at=time.time(),
            )
            log.error("[Worker-%d] failed '%s': %s", worker_id, task.pdf_name, exc)

        finally:
            work_queue.task_done()


def _extract_range(task: ExtractionTask):
    """
    Extract Consolidated FS from the page range identified by the Dispatcher.
    Uses a temp-file so pdf_parser.extract_local can work on just those pages.
    Falls back to the full-document path if page extraction fails.
    """
    from agents.extractor import extract_from_pdf_range
    return extract_from_pdf_range(
        path=task.pdf_path,
        start_page=task.start_page,
        end_page=task.end_page,
        company_name=task.company_name,
        fiscal_years=task.fiscal_years,
        currency=task.currency,
        unit=task.unit,
    )


# ── Result container ───────────────────────────────────────────────────────────

@dataclass
class MultiAgentResult:
    registry: TaskRegistry
    tasks:    List[ExtractionTask]
    summary:  dict


# ── Main entry point ───────────────────────────────────────────────────────────

def run_multi_agent_extraction(
    pdf_inputs:          List[dict],
    wait_for_completion: bool = True,
) -> MultiAgentResult:
    """
    Run the full multi-agent extraction pipeline.

    Parameters
    ----------
    pdf_inputs : list of dicts with keys:
        path          (str)  - path to PDF file  [required]
        company_name  (str)  - hint for extraction  [optional]
        fiscal_years  (list) - e.g. [2024, 2023]   [optional]
        currency      (str)  - default "INR"
        unit          (str)  - default "Crores"

    wait_for_completion : bool
        Block until every worker finishes. Set False to get a live registry
        reference and poll yourself.

    Returns
    -------
    MultiAgentResult with .registry, .tasks, .summary
    """
    if not pdf_inputs:
        raise ValueError("pdf_inputs must not be empty.")

    registry = TaskRegistry()

    # One queue (mailbox) per worker - preserves round-robin ordering
    worker_queues: List[queue.Queue] = [queue.Queue() for _ in range(NUM_WORKERS)]

    # Start worker threads
    workers: List[threading.Thread] = []
    for i in range(NUM_WORKERS):
        t = threading.Thread(
            target=_worker_loop,
            args=(i + 1, worker_queues[i], registry),
            name=f"ExtractionWorker-{i + 1}",
            daemon=True,
        )
        t.start()
        workers.append(t)

    log.info(
        "Dispatcher started. %d PDF(s), %d workers.",
        len(pdf_inputs), NUM_WORKERS,
    )

    # ── Dispatcher loop ──────────────────────────────────────────────────────
    for pdf_idx, pdf_input in enumerate(pdf_inputs):
        pdf_path = pdf_input.get("path", "")
        pdf_name = Path(pdf_path).name
        worker_idx      = pdf_idx % NUM_WORKERS   # 0-based
        assigned_worker = worker_idx + 1           # 1-based (for display)

        log.info(
            "Dispatcher: PDF %d/%d '%s' -> Worker-%d — scanning TOC…",
            pdf_idx + 1, len(pdf_inputs), pdf_name, assigned_worker,
        )

        # Run TOC Navigator
        try:
            toc: TOCResult = navigate_to_consolidated_fs(pdf_path)
        except Exception as exc:
            log.error(
                "Dispatcher: TOC navigation error for '%s': %s — creating failed task.",
                pdf_name, exc,
            )
            task = ExtractionTask(
                task_id=str(uuid.uuid4()),
                pdf_path=pdf_path,
                pdf_name=pdf_name,
                section_name="",
                start_page=0,
                end_page=0,
                assigned_worker=assigned_worker,
                state="failed",
                error=f"TOC navigation failed: {exc}",
            )
            registry.register(task)
            continue

        task = ExtractionTask(
            task_id=str(uuid.uuid4()),
            pdf_path=pdf_path,
            pdf_name=pdf_name,
            section_name=toc.section_name,
            start_page=toc.start_page,
            end_page=toc.end_page,
            assigned_worker=assigned_worker,
            toc_method=toc.method,
            company_name=pdf_input.get("company_name", ""),
            fiscal_years=pdf_input.get("fiscal_years", []),
            currency=pdf_input.get("currency", "INR"),
            unit=pdf_input.get("unit", "Crores"),
        )
        registry.register(task)

        log.info(
            "Dispatcher: '%s' CFS pages %d-%d (method=%s) queued for Worker-%d",
            pdf_name, toc.start_page, toc.end_page, toc.method, assigned_worker,
        )
        worker_queues[worker_idx].put(task)

    # Send shutdown sentinel to each worker
    for q in worker_queues:
        q.put(None)

    if wait_for_completion:
        log.info("Dispatcher: all PDFs dispatched — waiting for workers to finish…")
        for t in workers:
            t.join()
        summary = registry.summary()
        log.info("Pipeline complete: %s", summary)
    else:
        summary = registry.summary()

    return MultiAgentResult(
        registry=registry,
        tasks=registry.all_tasks(),
        summary=summary,
    )


# ── Pretty-print helper ────────────────────────────────────────────────────────

def print_status_table(result: MultiAgentResult) -> None:
    """Print a formatted status table to stdout."""
    tasks = sorted(result.tasks, key=lambda t: t.assigned_worker)
    header = (
        f"{'PDF':<30} {'Section':<38} {'Pages':>10} "
        f"{'Worker':<10} {'Method':<14} {'State':<12} {'Dur(s)':>7}"
    )
    print()
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for t in tasks:
        pages = f"{t.start_page}-{t.end_page}" if t.start_page else "N/A"
        dur   = str(t.duration_s) if t.duration_s is not None else "-"
        print(
            f"{t.pdf_name[:29]:<30} {t.section_name[:37]:<38} {pages:>10} "
            f"Worker-{t.assigned_worker:<4}  {t.toc_method:<14} {t.state:<12} {dur:>7}"
        )
        if t.error:
            print(f"  ERROR: {t.error}")
    print("=" * len(header))
    s = result.summary
    print(
        f"  Total: {s['total']}  |  "
        f"Completed: {s['completed']}  |  "
        f"Failed: {s['failed']}  |  "
        f"In-progress: {s['in_progress']}"
    )
    print()
