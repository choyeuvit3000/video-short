"""Job types the worker accepts. There is deliberately no generic "run a command" job.

`pipeline`: rebuild the project from its blobs in a private workspace, run the requested studio stages
(validate / voice / render / qc / package) with this machine's config (NVENC, CUDA whisper, GPU voices),
then store every new or changed file as a result blob.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..core.config import Settings, deep_merge
from ..core.errors import EXIT_ERROR, StudioError
from ..core.logging_utils import attach_run_log, detach_run_log, get_logger
from ..core.paths import resolve_inside
from ..core.project import ProjectContext
from ..nodes.bundle import RESULT_FILES, RESULT_PREFIXES, sha256_file
from ..nodes.remote import REMOTE_STAGES  # noqa: F401 - re-exported for the API schema
from ..pipeline.runner import RunOptions, run_pipeline, select_stages
from .store import BlobError, BlobStore

log = get_logger()

class JobCancelled(Exception):
    pass


def materialize(store: BlobStore, entries: list[dict[str, Any]], root: Path) -> dict[str, str]:
    snapshot = {}
    for e in entries:
        dest = resolve_inside(root, e["path"], what="job file")
        store.copy_to(e["sha256"], dest)
        snapshot[e["path"]] = e["sha256"]
    return snapshot


def collect_results(store: BlobStore, project: Path, before: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for p in sorted(project.rglob("*")):
        if not p.is_file() or p.suffix == ".tmp":
            continue
        rel = p.relative_to(project).as_posix()
        if not (rel in RESULT_FILES or rel.startswith(RESULT_PREFIXES)):
            continue
        if rel in before and sha256_file(p) == before[rel]:
            continue
        sha, size = store.put_file(p)
        out.append({"path": rel, "sha256": sha, "size": size})
    return out


def run_pipeline_job(job: dict[str, Any], *, store: BlobStore, settings: Settings, workspace: Path,
                     is_cancelled, on_stage, keep_workspace: bool = False) -> dict[str, Any]:
    """Returns {status, exit_code, error, result}. Never raises for pipeline failures."""
    req = job["request"]
    project = workspace / "project"
    overlay = workspace / "assets"
    if workspace.exists():  # leftover of an interrupted attempt
        shutil.rmtree(workspace)
    project.mkdir(parents=True)
    overlay.mkdir()
    status, code, error = "done", 0, None
    state: dict[str, Any] = {}
    files: list[dict[str, Any]] = []
    try:
        before = materialize(store, req["files"], project)
        materialize(store, req.get("assets", []), overlay)
        job_settings = Settings(root=settings.root, formats=settings.formats,
                               data=deep_merge(settings.data, {"paths": {"asset_overlay": str(overlay)}}))
        attach_run_log(project, f"worker_{job['id']}")
        log.info("[worker] job %s: stages %s", job["id"], ", ".join(req["stages"]))
        ctx = ProjectContext(project, settings=job_settings)
        opts = req.get("options") or {}
        stage_opts = {k: opts.get(k) for k in ("overwrite", "strict", "allow_sidecar", "burn_subs")}
        try:
            for stage in select_stages(ctx, RunOptions(only=list(req["stages"]))):
                if is_cancelled():
                    raise JobCancelled()
                on_stage(stage)
                run_pipeline(ctx, RunOptions(only=[stage], stage_opts=stage_opts))
        except JobCancelled:
            status, code, error = "cancelled", None, "cancelled before the next stage"
            log.warning("[worker] job %s cancelled", job["id"])
        except StudioError as e:
            status, code, error = "failed", e.exit_code, str(e)
            log.error("[worker] job %s failed: %s", job["id"], e)
        except Exception as e:  # unexpected - still return logs to the controller
            status, code, error = "failed", EXIT_ERROR, f"{type(e).__name__}: {e}"
            log.exception("[worker] job %s crashed", job["id"])
        finally:
            detach_run_log()
        state = ctx.state()
        files = collect_results(store, project, before)
    except (StudioError, BlobError, OSError) as e:  # materialize / project load problems
        detach_run_log()
        status, code, error = "failed", getattr(e, "exit_code", EXIT_ERROR), str(e)
    finally:
        if not keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)
    return {"status": status, "exit_code": code, "error": error, "result": {"files": files, "state": state}}
