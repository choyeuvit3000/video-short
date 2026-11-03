"""Stage runner: runs a workflow's stages in order, records state.json, stops at manual gates.

Re-running is always safe: generator stages (source/script/scenes/storyboard) keep their previous
output unless --force; voice uses the TTS cache; render/qc/package are rebuilt from the project.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..core.errors import EXIT_OK, ManualGateRequired, StudioError, ValidationError
from ..core.logging_utils import get_logger
from ..core.project import ProjectContext
from ..workflows import get_stages, load_workflow

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
    text = (f"# TODO (manual step) - {ctx.project.title or ctx.project.project_id}\n\n"
            f"Pipeline stopped at stage **{gate.stage}**. Do the steps below, then run again:\n\n"
            f"```powershell\nstudio run \"{ctx.dir}\"\n```\n\n{gate.instructions}")
    (ctx.dir / "TODO_MANUAL.md").write_text(text, encoding="utf-8")


def run_pipeline(ctx: ProjectContext, ro: RunOptions) -> int:
    names = stages_for(ctx)
    registry = get_stages()
    for n in [*ro.only, *([ro.from_stage] if ro.from_stage else [])]:
        if n not in names:
            raise ValidationError(f"stage '{n}' is not part of workflow {ctx.project.workflow}: {names}",
                                  code="bad_stage")
    if ro.only:
        selected = [n for n in names if n in ro.only]
    elif ro.from_stage:
        selected = names[names.index(ro.from_stage):]
    else:
        selected = names
    for name in selected:
        fn = registry.get(name)
        if fn is None:
            raise StudioError(f"stage '{name}' has no implementation", code="bad_stage")
        opts = {**ro.stage_opts, "force": ro.force}
        ctx.set_stage(name, "running")
        t0 = time.monotonic()
        try:
            msg = fn(ctx, opts)
        except ManualGateRequired as gate:
            write_todo(ctx, gate)
            ctx.set_stage(name, "waiting_manual", str(gate))
            log.warning("[%s] waiting for manual input -> %s", name, ctx.dir / "TODO_MANUAL.md")
            raise
        except StudioError as e:
            ctx.set_stage(name, "failed", str(e))
            raise
        except Exception as e:  # unexpected: record, then let the CLI report it
            ctx.set_stage(name, "failed", f"{type(e).__name__}: {e}")
            raise
        ctx.set_stage(name, "done", msg or "")
        log.info("[%s] done in %.1fs - %s", name, time.monotonic() - t0, msg)
    if selected and selected[-1] == names[-1]:
        (ctx.dir / "TODO_MANUAL.md").unlink(missing_ok=True)
    return EXIT_OK
