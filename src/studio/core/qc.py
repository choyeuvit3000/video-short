"""QC of output/final.mp4: container/codec vs the format profile and timeline, captions, and content
(loudness, silence, black/frozen frames, caption safe zone - see qc_analysis.py)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import FFmpegError, StudioError
from .media_probe import probe
from .project import ProjectContext
from .qc_analysis import analyze_av, caption_layout, overlap
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


def _content_checks(ctx: ProjectContext, final: Path, summary: dict, tl: dict | None,
                    errors: list[str], warnings: list[str]) -> dict[str, Any]:
    """Loudness, silence inside narration, black frames, frozen clips. Thresholds: settings `qc.*`."""
    cfg = ctx.settings.get
    duration = float(summary.get("duration_sec") or 0)
    max_sil = float(cfg("qc.max_silence_sec", 2.0))
    max_black = float(cfg("qc.max_black_sec", 0.5))
    max_freeze = float(cfg("qc.max_freeze_sec", 2.0))
    try:
        a = analyze_av(final, duration, min_silence=min(0.5, max_sil), min_freeze=min(1.0, max_freeze))
    except FFmpegError as e:
        warnings.append(f"content analysis skipped: {e}")
        return {}
    p = ctx.project
    scenes = list(zip(p.scenes, tl["scenes"], strict=False)) if tl else []
    has_audio_content = any(s.narration.strip() for s in p.scenes) or bool(p.audio.background_music)

    lufs, peak = a["integrated_lufs"], a["true_peak_db"]
    lo, hi = float(cfg("qc.loudness_min_lufs", -20)), float(cfg("qc.loudness_max_lufs", -9))
    if lufs is None:
        warnings.append("loudness could not be measured")
    elif has_audio_content and lufs < float(cfg("qc.silent_lufs", -50)):
        errors.append(f"audio is essentially silent ({lufs:.1f} LUFS) although the video has narration/music")
    elif has_audio_content and not lo <= lufs <= hi:
        warnings.append(f"loudness {lufs:.1f} LUFS outside {lo:g}..{hi:g} (platforms target about -14)")
    if peak is not None and peak > float(cfg("qc.max_true_peak_db", -0.5)):
        warnings.append(f"true peak {peak:.1f} dBFS - audio may clip")

    for s, sc in scenes:
        start = sc["start_ms"] / 1000
        if s.narration.strip() and sc.get("voice_ms"):
            # longest single gap - pauses between sentences are normal, a dead stretch is not
            gap = max((overlap([iv], start, start + sc["voice_ms"] / 1000) for iv in a["silence"]), default=0.0)
            if gap >= max_sil:
                warnings.append(f"{s.scene_id}: {gap:.1f}s of continuous silence inside the narration")
        end = start + sc["duration_ms"] / 1000
        if s.visual.type != "color":
            dark = overlap(a["black"], start, end)
            if dark >= max_black:
                warnings.append(f"{s.scene_id}: {dark:.1f}s of black frames")
        if s.visual.type == "clip":
            frozen = overlap(a["freeze"], start, end)
            if frozen >= max_freeze:
                warnings.append(f"{s.scene_id}: clip frozen for {frozen:.1f}s")
    black_total = overlap(a["black"], 0, duration)
    if duration and black_total > duration / 2 and not all(s.visual.type == "color" for s in p.scenes):
        errors.append(f"{black_total:.1f}s of {duration:.1f}s is black - missing or broken visuals?")
    return {"audio": {"integrated_lufs": lufs, "true_peak_db": peak, "silences": a["silence"]},
            "video": {"black": a["black"], "freeze": a["freeze"]}}


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
    tl: dict[str, Any] = {}
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

    checks: dict[str, Any] = {}
    if summary and ctx.settings.get("qc.analyze", True):
        checks.update(_content_checks(ctx, final, summary, tl if scenes_processed else None, errors, warnings))
    ass = ctx.work / "captions.ass"
    if (summary and p.video.subtitle_mode == "burn_in" and has_narration and ass.is_file()
            and ctx.settings.get("qc.caption_safe_area", True)):
        lay = caption_layout(ass, width=fmt.width, height=fmt.height, safe=fmt.safe_zone,
                             font_dirs=[ctx.asset_dir("shared/fonts")])
        checks["captions"] = lay
        if lay["outside_frame"]:
            errors.append(f"{len(lay['outside_frame'])} caption(s) run off the frame, e.g. "
                          f"{lay['outside_frame'][0]!r} - shorten words or lower caption.font_size")
        if lay["outside_safe_zone"]:
            warnings.append(f"{len(lay['outside_safe_zone'])} caption(s) leave the safe zone, e.g. "
                            f"{lay['outside_safe_zone'][0]!r}")

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
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }
    (out / "qc_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
