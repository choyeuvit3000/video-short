"""Stages shared by every workflow: validate -> voice -> render -> qc -> package."""

from __future__ import annotations

import json

from ..core.errors import QCFailed, ValidationError
from ..core.logging_utils import get_logger
from ..core.metadata import write_metadata
from ..core.project import ProjectContext
from ..core.qc import run_qc
from ..core.validator import validate_project
from ..pipeline.voice import run_voice
from ..renderers.render import render_project

log = get_logger()


def stage_validate(ctx: ProjectContext, opts: dict) -> str:
    issues = validate_project(ctx, require_media=True)
    errors = [i for i in issues if i.level == "error"]
    for i in issues:
        (log.error if i.level == "error" else log.warning)("[validate] %s", i)
    if errors:
        raise ValidationError(f"{len(errors)} validation error(s) - see log above", code="validation_failed")
    if not ctx.project.scenes:
        raise ValidationError("project has no scenes", code="no_scenes")
    return f"{len(ctx.project.scenes)} scenes OK, {len(issues)} warning(s)"


def stage_voice(ctx: ProjectContext, opts: dict) -> str:
    tl = run_voice(ctx, overwrite=bool(opts.get("overwrite")))
    return f"{tl['total_ms'] / 1000:.2f}s, voice={tl['voice_profile']}"


def stage_render(ctx: ProjectContext, opts: dict) -> str:
    out = render_project(ctx, burn_subs=opts.get("burn_subs"), allow_sidecar=bool(opts.get("allow_sidecar")))
    return str(out)


def stage_qc(ctx: ProjectContext, opts: dict) -> str:
    rep = run_qc(ctx)
    if rep["status"] != "PASS":
        raise QCFailed("QC failed: " + "; ".join(rep["errors"]), code="qc_failed")
    if opts.get("strict") and rep.get("warnings"):
        raise QCFailed("QC strict: warnings present: " + "; ".join(rep["warnings"]), code="qc_strict")
    return f"PASS ({len(rep.get('warnings', []))} warning(s))"


def stage_package(ctx: ProjectContext, opts: dict) -> str:
    write_metadata(ctx)
    plan = write_scene_plan(ctx)
    return str(ctx.result_path("metadata.md")) + (f", {plan}" if plan else "")


def write_scene_plan(ctx: ProjectContext) -> str | None:
    """output/scene_plan.json for workflows that plan scenes (`scene.plan`): start/end, spoken line, layout,
    asset or fallback with its reason, source, on-screen text, crop focus - one row per scene, for review."""
    if not any(getattr(s, "plan", None) for s in ctx.project.scenes):
        return None
    tl = ctx.load_timeline()
    times = {sc["scene_id"]: sc for sc in tl["scenes"]}
    rows = []
    for s in ctx.project.scenes:
        sc = times.get(s.scene_id, {})
        start = sc.get("start_ms", 0)
        rows.append({"scene_id": s.scene_id, "start_sec": round(start / 1000, 2),
                     "end_sec": round((start + sc.get("duration_ms", 0)) / 1000, 2),
                     "timing_source": sc.get("timing_source"), "narration": s.narration,
                     **(getattr(s, "plan", None) or {})})
    out = ctx.result_path("scene_plan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(out)


COMMON_STAGES = {
    "validate": stage_validate,
    "voice": stage_voice,
    "render": stage_render,
    "qc": stage_qc,
    "package": stage_package,
}
