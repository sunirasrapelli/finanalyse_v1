"""
Structured logging: writes to console (INFO+) and a rotating daily log
file under outputs/logs/ (DEBUG+, max 10 MB, 5 backups).
"""
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import LOGS_DIR

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def get_logger(name: str = __name__) -> logging.Logger:
    """
    Return a named logger.  Calling with the same *name* twice returns the
    same logger instance (stdlib guarantee), so handlers are attached only
    once even if get_logger() is called from multiple modules.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured — skip re-attaching handlers

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    # Console — INFO and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    # Rotating file — DEBUG and above, one file per calendar day,
    # rotated at 10 MB, keeping the last 5 files.
    log_file: Path = LOGS_DIR / f"{datetime.now().strftime('%Y%m%d')}.log"
    fh = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger
