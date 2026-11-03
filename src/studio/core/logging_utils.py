"""Per-run log file in <project>/logs/run_<timestamp>.log plus a rich console handler."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console(highlight=False)

_SECRET_RES = [
    # key=value, key: value, "key": "value", ?access_token=... (the name may be a suffix: THREADS_ACCESS_TOKEN=)
    re.compile(r"(?i)(\w*(?:api[_-]?key|token|secret|password))([\"']?\s*[=:]\s*[\"']?)(?!\*\*\*)([^\s\"'&,]+)"),
    re.compile(r"(?i)(authorization[\"']?\s*[=:]\s*[\"']?(?:bearer|basic|token)?\s*)(?!\*\*\*)([^\s\"'&,]+)"),
    re.compile(r"(?i)(\bbearer\s+)(?!\*\*\*)([A-Za-z0-9._~+/=-]{8,})"),
]


def redact(text: str) -> str:
    """Mask secret values; prose such as 'THREADS_ACCESS_TOKEN not set' is left readable."""
    for rx in _SECRET_RES:
        text = rx.sub(lambda m: "".join(m.groups()[:-1]) + "***", text)
    return text


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        return True


def get_logger() -> logging.Logger:
    log = logging.getLogger("studio")
    if not log.handlers:
        log.setLevel(logging.DEBUG)
        h = RichHandler(console=console, show_path=False, show_time=False, markup=False)
        h.setLevel(logging.INFO)
        h.addFilter(_RedactFilter())
        log.addHandler(h)
    return log


def attach_run_log(project_dir: Path, command: str) -> Path:
    """Add a file handler for this run; returns the log path."""
    log = get_logger()
    for h in list(log.handlers):
        if isinstance(h, logging.FileHandler):
            log.removeHandler(h)
            h.close()
    logs = project_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{command}.log"
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    fh.addFilter(_RedactFilter())
    log.addHandler(fh)
    return path


def detach_run_log() -> None:
    """Close the per-run file handler (the worker must release it before deleting a job folder)."""
    log = get_logger()
    for h in list(log.handlers):
        if isinstance(h, logging.FileHandler):
            log.removeHandler(h)
            h.close()
