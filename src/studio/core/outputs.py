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


def archive_project(ctx) -> Path | None:
    """Archive only this project's centrally named artifacts, never another mode's files."""
    keep = int(ctx.settings.get("output.keep_history", 3))
    if not ctx.settings.get("paths.output"):
        return archive_previous(ctx.output, keep)
    final = ctx.final_video
    if keep <= 0 or not final.is_file():
        return None
    hist = final.parent / "_history" / ctx.result_stem
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = hist / stamp
    dest.mkdir(parents=True)
    for name in (*ARCHIVED, "scene_plan.json"):
        source = ctx.result_path(name)
        if source.is_file():
            source.replace(dest / source.name)
    for old in sorted(hist.iterdir())[:-keep]:
        if old.is_dir():
            shutil.rmtree(old)
    return dest


def organized_output(root: Path, mode: str, state_file: Path) -> Path:
    """Group deliverables by Bangkok date/mode; persist the date for resume and QC."""
    import json
    import re
    from datetime import date
    from zoneinfo import ZoneInfo
    mode = re.sub(r"[^A-Za-z0-9_-]+", "-", mode).strip("-") or "video"
    if state_file.is_file():
        data = json.loads(state_file.read_text(encoding="utf-8"))
        day = date.fromisoformat(data["date"]).isoformat()
    else:
        day = datetime.now(ZoneInfo("Asia/Bangkok")).date().isoformat()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = state_file.with_suffix(".tmp")
        temp.write_text(json.dumps({"date": day, "mode": mode}), encoding="utf-8")
        temp.replace(state_file)
    folder = root / day / mode
    folder.mkdir(parents=True, exist_ok=True)
    return folder
