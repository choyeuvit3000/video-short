"""Technical QC of output/final.mp4 against the project's format profile and timeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import StudioError
from .media_probe import probe
from .project import ProjectContext
from .subtitles import check_cues, read_srt


def check_media(path: Path, *, width: int, height: int, fps: int, expected_sec: float | None,
                tolerance_sec: float) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        info = probe(path)
    except StudioError as e:
        return {}, [str(e)], warnings
    summary = {
        "duration_sec": round(info.duration, 3),
        "video": {"width": info.width, "height": info.height, "fps": round(info.fps, 3), "codec": info.vcodec,
                  "pix_fmt": info.pix_fmt, "sar": info.sar},
        "audio": {"codec": info.acodec, "sample_rate": info.sample_rate, "channels": info.channels},
    }
    if not info.has_video:
        errors.append("no video stream")
    else:
        if (info.width, info.height) != (width, height):
            errors.append(f"resolution {info.width}x{info.height} != {width}x{height}")
        if abs(info.fps - fps) > 0.05:
            errors.append(f"fps {info.fps:.3f} != {fps}")
        if info.vcodec != "h264":
            errors.append(f"video codec {info.vcodec} != h264")
        if info.pix_fmt != "yuv420p":
            errors.append(f"pix_fmt {info.pix_fmt} != yuv420p")
        if info.sar not in (None, "1:1", "0:1"):
            errors.append(f"SAR {info.sar} != 1:1")
    if not info.has_audio:
        errors.append("no audio stream (a silent AAC track is required)")
    else:
        if info.acodec != "aac":
            errors.append(f"audio codec {info.acodec} != aac")
        if info.sample_rate != 48000:
            errors.append(f"sample rate {info.sample_rate} != 48000")
        if info.channels != 2:
            errors.append(f"channels {info.channels} != 2")
    if expected_sec is not None and abs(info.duration - expected_sec) > tolerance_sec:
        errors.append(f"duration {info.duration:.2f}s != expected {expected_sec:.2f}s (±{tolerance_sec}s)")
    return summary, errors, warnings


def run_qc(ctx: ProjectContext) -> dict[str, Any]:
    p = ctx.project
    fmt = ctx.fmt
    out = ctx.output
    final = out / "final.mp4"
    tol = float(ctx.settings.get("qc.duration_tolerance_sec", 0.3))
    max_chars = int(ctx.settings.get("qc.max_caption_chars_per_line", 42))
    warnings: list[str] = []
    errors: list[str] = []
    expected: float | None = None
    scenes_processed = 0
    try:
        tl = ctx.load_timeline()
        expected = tl["total_ms"] / 1000
        scenes_processed = len(tl["scenes"])
        warnings.extend(tl.get("warnings", []))
    except StudioError as e:
        errors.append(str(e))
    if scenes_processed != len(p.scenes):
        errors.append(f"timeline has {scenes_processed} scenes, project has {len(p.scenes)}")

    summary, errs, warns = check_media(final, width=fmt.width, height=fmt.height, fps=fmt.fps,
                                        expected_sec=expected, tolerance_sec=tol)
    errors += errs
    warnings += warns

    srt = out / "captions.srt"
    has_narration = any(s.narration.strip() for s in p.scenes)
    if p.video.subtitle_mode != "none" and has_narration:
        if not srt.exists():
            errors.append("captions.srt missing")
        else:
            try:
                cues = read_srt(srt)
                dur_ms = int(summary.get("duration_sec", 0) * 1000) or None
                errors += [f"captions.srt: {m}" for m in check_cues(cues, duration_ms=dur_ms)]
                long_lines = sum(1 for c in cues for ln in c.text.split("\n") if len(ln) > max_chars)
                if long_lines:
                    warnings.append(f"{long_lines} caption line(s) longer than {max_chars} chars")
            except (StudioError, UnicodeDecodeError) as e:
                errors.append(f"captions.srt unreadable: {e}")

    report = {
        "project_id": p.project_id,
        "workflow": p.workflow,
        "format": fmt.name,
        "status": "PASS" if not errors else "FAIL",
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "output_path": "output/final.mp4",
        "expected_duration_sec": expected,
        "actual_duration_sec": summary.get("duration_sec"),
        "video": summary.get("video"),
        "audio": summary.get("audio"),
        "scenes_processed": scenes_processed,
        "warnings": warnings,
        "errors": errors,
    }
    (out / "qc_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
