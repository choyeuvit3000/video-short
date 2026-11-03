"""Output history: a new final render never destroys the previous one.

Before output/final.mp4 is replaced, the current final video and the files that describe it (captions,
QC report, metadata) move to output/history/<time of that render>/. Only the newest `output.keep_history`
versions are kept (0 = keep none, the old overwrite behaviour). Only generated files live here.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .logging_utils import get_logger

log = get_logger()

ARCHIVED = ("final.mp4", "captions.srt", "qc_report.json", "metadata.md")


def archive_previous(out_dir: Path, keep: int) -> Path | None:
    """Move the current final render into output/history/; returns the new folder (None if nothing moved)."""
    final = out_dir / "final.mp4"
    if keep <= 0 or not final.is_file():
        return None
    hist = out_dir / "history"
    stamp = datetime.fromtimestamp(final.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
    dest = hist / stamp
    n = 1
    while dest.exists():
        n += 1
        dest = hist / f"{stamp}_{n}"
    dest.mkdir(parents=True)
    for name in ARCHIVED:
        src = out_dir / name
        if src.is_file():
            src.replace(dest / name)
    log.info("[output] previous render kept in %s", dest)
    old = sorted((d for d in hist.iterdir() if d.is_dir()), key=lambda d: d.name)
    for d in old[:-keep]:
        shutil.rmtree(d, ignore_errors=True)
    return dest
