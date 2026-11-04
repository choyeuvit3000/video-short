"""Stages shared by every workflow: validate -> voice -> render -> qc -> package."""

from __future__ import annotations

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
    return str(ctx.result_path("metadata.md"))


COMMON_STAGES = {
    "validate": stage_validate,
    "voice": stage_voice,
    "render": stage_render,
    "qc": stage_qc,
    "package": stage_package,
}
