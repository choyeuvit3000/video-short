"""Stage fingerprints: render / qc / package are skipped when nothing they read has changed.

A fingerprint hashes everything a stage reads: the relevant part of project.json, the timeline and word
timings, the content (sha256) of every media file and asset it uses, the format profile and the stage's
settings. After a successful run the runner stores it in state.json together with the sha256 of each output.
A later run skips the stage only if the fingerprint is identical AND every output is still there unchanged.

Machine-specific choices that do not change the result (render.encoder, ffmpeg build) are left out, so a
video rendered on the GPU worker is not rendered again on the laptop. Bump REV when the output of render,
qc or package changes for the same inputs.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..core.cache import cache_key
from ..core.errors import StudioError
from ..core.project import ProjectContext

REV = 2

SKIPPABLE = ("render", "qc", "package")
MACHINE_KEYS = {"encoder"}  # render.* keys that only change speed, not the picture


def _sha(ctx: ProjectContext, path: Path) -> str | None:
    return ctx.hashes.sha(path) if path.is_file() else None


def _ref_sha(ctx: ProjectContext, ref: str | None, what: str) -> str | None:
    if not ref or ref == "gradient" or ref.startswith("color:"):
        return ref
    try:
        return _sha(ctx, ctx.resolve(ref, what=what))
    except StudioError:
        return None


def _render_inputs(ctx: ProjectContext) -> dict[str, Any]:
    p = ctx.project
    render_cfg = {k: v for k, v in (ctx.settings.get("render") or {}).items() if k not in MACHINE_KEYS}
    tl = ctx.timeline_path()
    media = {}
    for s in p.scenes:
        media[s.scene_id] = [_ref_sha(ctx, s.visual.path, "clip"), _ref_sha(ctx, s.visual.overlay, "overlay")]
    audio = {}
    if tl.is_file():
        for sc in json.loads(tl.read_text(encoding="utf-8")).get("scenes", []):
            if sc.get("audio"):
                audio[sc["scene_id"]] = _sha(ctx, ctx.dir / sc["audio"])
    fonts = ctx.asset_dir("shared/fonts")
    font_shas = sorted((f.name, ctx.hashes.sha(f)) for f in fonts.iterdir() if f.is_file()) if fonts.is_dir() else []
    return {
        "video": p.video.model_dump(mode="json"),
        "audio": p.audio.model_dump(mode="json"),
        "timing": p.timing_mode,
        "scenes": [s.model_dump(mode="json") for s in p.scenes],
        "format": asdict(ctx.fmt),
        "render": render_cfg,
        "timeline": _sha(ctx, tl),
        "words": _sha(ctx, ctx.work / "words.json"),
        "media": media,
        "narration": audio,
        "background": _ref_sha(ctx, p.video.background, "background"),
        "music": _ref_sha(ctx, p.audio.background_music, "music"),
        "caption_style": _ref_sha(ctx, f"asset:shared/caption_styles/{p.video.caption_style}.yaml", "style"),
        "fonts": font_shas,
    }


def outputs_for(ctx: ProjectContext, stage: str) -> list[str]:
    if stage == "render":
        outs = ["output/final.mp4"]
        if (ctx.output / "captions.srt").exists():
            outs.append("output/captions.srt")
        return outs
    if stage == "qc":
        return ["output/qc_report.json"]
    if stage == "package":
        return ["output/metadata.md"]
    return []


def compute(ctx: ProjectContext, stage: str, opts: dict) -> str | None:
    """Fingerprint of everything `stage` reads, or None for stages that always run."""
    if stage not in SKIPPABLE:
        return None
    out = ctx.output
    if stage == "render":
        data: dict[str, Any] = _render_inputs(ctx)
        data["opts"] = {"burn_subs": opts.get("burn_subs"), "allow_sidecar": bool(opts.get("allow_sidecar"))}
    elif stage == "qc":
        data = {
            "final": _sha(ctx, out / "final.mp4"),
            "srt": _sha(ctx, out / "captions.srt"),
            "timeline": _sha(ctx, ctx.timeline_path()),
            "qc": ctx.settings.get("qc") or {},
            "format": asdict(ctx.fmt),
            "video": ctx.project.video.model_dump(mode="json"),
            "scenes": [[s.scene_id, s.visual.type, bool(s.narration.strip())] for s in ctx.project.scenes],
            "strict": bool(opts.get("strict")),
        }
    else:  # package
        data = {
            "project": ctx.project.model_dump(mode="json"),
            "final": _sha(ctx, out / "final.mp4"),
            "qc": _sha(ctx, out / "qc_report.json"),
        }
    return cache_key(stage, REV, data)


def output_shas(ctx: ProjectContext, stage: str) -> dict[str, str | None]:
    return {rel: _sha(ctx, ctx.dir / rel) for rel in outputs_for(ctx, stage)}


def up_to_date(ctx: ProjectContext, stage: str, fingerprint: str | None) -> bool:
    if fingerprint is None:
        return False
    entry = ctx.state().get("stages", {}).get(stage) or {}
    if entry.get("status") != "done" or entry.get("fingerprint") != fingerprint:
        return False
    recorded = entry.get("outputs") or {}
    if not recorded:
        return False
    return all(sha is not None and _sha(ctx, ctx.dir / rel) == sha for rel, sha in recorded.items())
