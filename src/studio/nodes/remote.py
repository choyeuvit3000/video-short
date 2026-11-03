"""Controller side of remote runs: submit a project's remote stages to a node, wait, pull results back.

Records: <project>/work/remote_job.json (last job of this project) and cache/remote_jobs.json (index of
all jobs, so `studio jobs pull <job_id>` finds the project folder).
"""

from __future__ import annotations

import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.errors import EXIT_ERROR, EXIT_OK, StudioError, ValidationError, WaitingForNode
from ..core.logging_utils import get_logger
from ..core.paths import atomic_replace
from ..core.project import ProjectContext
from .bundle import HashCache, apply_results, asset_manifest, merge_state, project_manifest
from .client import NodeClient

log = get_logger()

REMOTE_STAGES = ("validate", "voice", "render", "qc", "package")
TERMINAL = ("done", "failed", "cancelled")


def split_stages(selected: list[str]) -> tuple[list[str], list[str]]:
    """Generator stages (source/script/...) stay local; from the first remote-capable stage on, all go remote."""
    for i, name in enumerate(selected):
        if name in REMOTE_STAGES:
            rest = selected[i:]
            bad = [n for n in rest if n not in REMOTE_STAGES]
            if bad:
                raise ValidationError(f"stages {bad} cannot run on a worker", code="bad_stage")
            return selected[:i], rest
    return selected, []


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    atomic_replace(tmp, path)


def _index_path(ctx_or_settings) -> Path:
    s = getattr(ctx_or_settings, "settings", ctx_or_settings)
    return s.path("cache") / "remote_jobs.json"


def load_index(settings) -> dict[str, Any]:
    p = _index_path(settings)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_path(ctx: ProjectContext) -> Path:
    return ctx.work / "remote_job.json"


def load_record(ctx: ProjectContext) -> dict[str, Any] | None:
    p = record_path(ctx)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def submit_project(ctx: ProjectContext, client: NodeClient, stages: list[str], options: dict[str, Any]) -> str:
    hc = HashCache(ctx.settings.path("cache") / "hashes.json")
    files = project_manifest(ctx, hc, include_output="render" not in stages)
    assets = asset_manifest(ctx, hc)
    hc.save()
    local = {e["sha256"]: ctx.dir / e["path"] for e in files}
    local.update({e["sha256"]: ctx.resolve("asset:" + e["path"]) for e in assets})
    missing = client.missing(list(local))
    total = sum(local[s].stat().st_size for s in missing)
    log.info("[remote] %s: %d files + %d assets, uploading %d new blob(s) (%.1f MB)", client.node_id,
             len(files), len(assets), len(missing), total / 1e6)
    for sha in missing:
        client.upload(sha, local[sha])
    req = {"type": "pipeline", "project_id": ctx.project.project_id, "stages": stages, "files": files,
           "assets": assets, "options": {k: v for k, v in options.items() if v is not None},
           "client": platform.node()[:64] or None}
    resp = client.submit(req)
    job_id = resp["id"]
    rec = {"node": client.node_id, "job_id": job_id, "stages": stages, "project_dir": str(ctx.dir),
           "submitted_at": datetime.now(UTC).isoformat(timespec="seconds"), "pulled": False,
           "uploaded": {e["path"]: e["sha256"] for e in files}}
    _write_json(record_path(ctx), rec)
    idx = load_index(ctx.settings)
    idx[job_id] = {k: rec[k] for k in ("node", "project_dir", "stages", "submitted_at")}
    _write_json(_index_path(ctx), idx)
    for s in stages:
        ctx.set_stage(s, "remote", f"{client.node_id}:{job_id}")
    if resp.get("paused_reason"):
        log.warning("[remote] node %s is paused (%s) - the job waits in its queue", client.node_id,
                    resp["paused_reason"])
    log.info("[remote] submitted job %s to %s", job_id, client.node_id)
    return job_id


def wait_for_job(client: NodeClient, job_id: str, *, poll_sec: float, timeout_sec: float,
                 sleep=time.sleep) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last = None
    while True:
        job = client.job(job_id)
        if job["status"] in TERMINAL:
            return job
        state = (job["status"], job.get("stage"))
        if state != last:
            log.info("[remote] job %s: %s%s", job_id, job["status"], f" ({job['stage']})" if job.get("stage") else "")
            last = state
        if job["status"] == "queued":
            h = client.health()
            if h.get("paused_reason") and not h.get("in_schedule", True):
                raise WaitingForNode(f"job {job_id} is queued on {client.node_id}, which is {h['paused_reason']}")
        if time.monotonic() > deadline:
            raise WaitingForNode(f"job {job_id} still {job['status']} on {client.node_id} after "
                                 f"{timeout_sec / 60:.0f} min")
        sleep(poll_sec)


def pull_job(ctx: ProjectContext, client: NodeClient, job_id: str) -> int:
    """Apply a finished job to the project. Returns the job's exit code (WaitingForNode if not finished)."""
    job = client.job(job_id)
    if job["status"] not in TERMINAL:
        raise WaitingForNode(f"job {job_id} is {job['status']} on {client.node_id} - pull again later")
    rec = load_record(ctx) or {}
    uploaded = rec.get("uploaded", {}) if rec.get("job_id") == job_id else {}
    result = job.get("result") or {}
    stats = apply_results(ctx, result.get("files", []), uploaded, client.download)
    merge_state(ctx, result.get("state") or {}, job.get("stages", []), client.node_id)
    if rec.get("job_id") == job_id:
        rec.update({"pulled": True, "status": job["status"],
                    "pulled_at": datetime.now(UTC).isoformat(timespec="seconds")})
        _write_json(record_path(ctx), rec)
    log.info("[remote] pulled job %s (%s): %d written, %d unchanged, %d conflict(s)", job_id, job["status"],
             stats["written"], stats["same"], stats["conflict"])
    if job["status"] == "done":
        return EXIT_OK
    err = StudioError(f"remote job {job_id} {job['status']}: {job.get('error') or '-'}", code="remote_failed")
    err.exit_code = job.get("exit_code") or EXIT_ERROR
    raise err
