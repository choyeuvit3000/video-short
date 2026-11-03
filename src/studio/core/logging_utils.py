"""Per-run log file in <project>/logs/run_<timestamp>.log plus a rich console handler."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console(highlight=False)

_SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|authorization|password)([=:\s\"']+)([^\s\"']+)")


def redact(text: str) -> str:
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


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
