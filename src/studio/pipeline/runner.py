"""Stage runner: runs a workflow's stages in order, records state.json, stops at manual gates.

Re-running is always safe: generator stages (source/script/scenes/storyboard) keep their previous
output unless --force; voice uses the TTS cache; render/qc/package are skipped when their fingerprint
(pipeline/fingerprint.py) and outputs are unchanged, otherwise rebuilt from the project. --force rebuilds all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..core.errors import EXIT_OK, ManualGateRequired, StudioError, ValidationError
from ..core.logging_utils import get_logger
from ..core.project import ProjectContext
from ..workflows import get_stages, load_workflow
from . import fingerprint

log = get_logger()


@dataclass
class RunOptions:
    from_stage: str | None = None
    only: list[str] = field(default_factory=list)
    force: bool = False
    stage_opts: dict = field(default_factory=dict)  # overwrite, burn_subs, allow_sidecar, strict


def stages_for(ctx: ProjectContext) -> list[str]:
    return list(load_workflow(ctx.settings, ctx.project.workflow)["stages"])


def write_todo(ctx: ProjectContext, gate: ManualGateRequired) -> None:
    text = (
        f"# TODO (manual step) - {ctx.project.title or ctx.project.project_id}\n\n"
        f"Pipeline stopped at stage **{gate.stage}**. Do the steps below, then run again:\n\n"
        f'```powershell\nstudio run "{ctx.dir}"\n```\n\n{gate.instructions}'
    )
    (ctx.dir / "TODO_MANUAL.md").write_text(text, encoding="utf-8")


def select_stages(ctx: ProjectContext, ro: RunOptions) -> list[str]:
    names = stages_for(ctx)
    for n in [*ro.only, *([ro.from_stage] if ro.from_stage else [])]:
        if n not in names:
            raise ValidationError(
                f"stage '{n}' is not part of workflow {ctx.project.workflow}: {names}", code="bad_stage"
            )
    if ro.only:
        return [n for n in names if n in ro.only]
    if ro.from_stage:
        return names[names.index(ro.from_stage) :]
    return names


def run_pipeline(ctx: ProjectContext, ro: RunOptions) -> int:
    try:
        return _run(ctx, ro)
    finally:
        ctx.save_hashes()


def _run(ctx: ProjectContext, ro: RunOptions) -> int:
    names = stages_for(ctx)
    registry = get_stages()
    selected = select_stages(ctx, ro)
    for name in selected:
        if ctx.settings.get("reviews.required", True) and name in {"voice", "render"}:
            from ..core.user_review import checkpoint

            checkpoint(ctx.dir, "script" if name == "voice" else "voice")
        if ctx.project.audio.source != "manual" and name in {"voice", "render"}:
            from ..voices import load_registry
            from .voice import choose_profile

            choose_profile(ctx, load_registry(ctx.settings))
        fn = registry.get(name)
        if fn is None:
            raise StudioError(f"stage '{name}' has no implementation", code="bad_stage")
        opts = {**ro.stage_opts, "force": ro.force}
        fp = fingerprint.compute(ctx, name, opts)
        if not ro.force and fingerprint.up_to_date(ctx, name, fp):
            prev = ctx.state()["stages"][name]
            log.info("[%s] up to date - skipped (inputs unchanged; --force to rebuild)", name)
            ctx.set_stage(name, "done", prev.get("message", ""), fingerprint=fp, outputs=prev["outputs"], skipped=True)
            continue
        if ctx.settings.get("planning.required", False) and name in {"voice", "render"}:
            from ..core.creative_brief import ensure_ready, reserve_render

            ensure_ready(ctx.dir)
            if name == "render":
                reserve_render(ctx.dir, fp or "render")
        ctx.set_stage(name, "running")
        t0 = time.monotonic()
        tracked_render = name == "render" and ctx.settings.get("planning.required", False)
        try:
            msg = fn(ctx, opts)
        except ManualGateRequired as gate:
            if tracked_render:
                from ..core.creative_brief import finish_render

                finish_render(ctx.dir, False)
            write_todo(ctx, gate)
            ctx.set_stage(name, "waiting_manual", str(gate))
            log.warning("[%s] waiting for manual input -> %s", name, ctx.dir / "TODO_MANUAL.md")
            raise
        except StudioError as e:
            if tracked_render:
                from ..core.creative_brief import finish_render

                finish_render(ctx.dir, False)
            ctx.set_stage(name, "failed", str(e))
            raise
        except Exception as e:  # unexpected: record, then let the CLI report it
            if tracked_render:
                from ..core.creative_brief import finish_render

                finish_render(ctx.dir, False)
            ctx.set_stage(name, "failed", f"{type(e).__name__}: {e}")
            raise
        if tracked_render:
            from ..core.creative_brief import finish_render

            finish_render(ctx.dir, True)
        extra = {"fingerprint": fp, "outputs": fingerprint.output_shas(ctx, name)} if fp else {}
        ctx.set_stage(name, "done", msg or "", **extra)
        log.info("[%s] done in %.1fs - %s", name, time.monotonic() - t0, msg)
        if name == "voice" and ctx.settings.get("reviews.required", True):
            from ..core.user_review import checkpoint

            checkpoint(ctx.dir, "voice")
    if selected and selected[-1] == names[-1]:
        (ctx.dir / "TODO_MANUAL.md").unlink(missing_ok=True)
    if ctx.settings.get("reviews.required", True) and any(n in {"voice", "render"} for n in selected):
        from ..core.user_review import checkpoint

        stage = "final" if "render" in selected else "voice"
        if stage == "final" and "qc" not in selected:
            from ..core.qc import run_qc

            run_qc(ctx)
        checkpoint(ctx.dir, stage)
    return EXIT_OK
