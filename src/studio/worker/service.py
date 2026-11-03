"""Worker service: owns the queue + blob store and runs one job at a time inside the node's schedule.

Config: `worker:` in config/studio.yaml (+ config/local.yaml on the worker machine). The token comes from
the node's `token_env` in config/nodes.yaml (same variable name in .env on both machines).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .. import __version__
from ..core.config import Settings
from ..core.errors import ValidationError
from ..core.logging_utils import get_logger
from ..nodes import Node, Schedule, load_nodes
from .jobs import run_pipeline_job
from .queue import JobQueue
from .store import BlobStore

log = get_logger()

MIN_TOKEN_LEN = 24
JOB_RUNNERS = {"pipeline": run_pipeline_job}


def user_idle_seconds() -> float | None:
    """Seconds since the last keyboard/mouse input in this Windows session (None elsewhere)."""
    if sys.platform != "win32":
        return None

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0


def gpu_status() -> dict[str, Any] | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    name, util, used, total = (x.strip() for x in out.stdout.strip().splitlines()[0].split(","))
    return {"name": name, "util_pct": int(util), "mem_used_mb": int(used), "mem_total_mb": int(total)}


class WorkerService:
    def __init__(self, settings: Settings, *, token: str | None = None, data_dir: Path | None = None,
                 ignore_schedule: bool | None = None, idle_probe=user_idle_seconds, gpu_probe=gpu_status):
        self.settings = settings
        w = settings.get("worker", {}) or {}
        self.node_id: str = w.get("node_id") or "worker"
        nodes = load_nodes(settings)
        self.node: Node | None = nodes.get(self.node_id)
        if token is None:
            env = self.node.token_env if self.node and self.node.token_env else "STUDIO_WORKER_TOKEN"
            token = os.environ.get(env, "")
            if len(token) < MIN_TOKEN_LEN:
                raise ValidationError(f"worker token missing or shorter than {MIN_TOKEN_LEN} chars: set {env} in .env",
                                      code="worker_token")
        self.token = token
        self.data_dir = Path(data_dir or w.get("data_dir") or settings.root / "worker_data")
        self.store = BlobStore(self.data_dir / "blobs", int(float(w.get("max_upload_gb", 8)) * 1024 ** 3))
        self.queue = JobQueue(self.data_dir / "queue.db")
        self.schedule: Schedule = self.node.schedule if self.node else Schedule()
        self.policy = self.node.policy if self.node else {}
        self.ignore_schedule = bool(w.get("ignore_schedule", False)) if ignore_schedule is None else ignore_schedule
        self.poll_sec = float(w.get("poll_sec", 5))
        self.keep_workspace = bool(w.get("keep_workspace", False))
        self.retention_days = float(w.get("retention_days", 7))
        self.idle_minutes = float(w.get("idle_minutes", 10))
        self.busy_gpu_util = int(w.get("busy_gpu_util", 40))
        self._idle_probe, self._gpu_probe = idle_probe, gpu_probe
        self._gpu_cache: tuple[float, Any] = (0.0, None)
        self.current_job: str | None = None

    # ------------------------------------------------------------------ policy
    def gpu(self) -> dict[str, Any] | None:
        t, val = self._gpu_cache
        if time.monotonic() - t > 10:
            val = self._gpu_probe()
            self._gpu_cache = (time.monotonic(), val)
        return val

    def in_schedule(self) -> bool:
        return self.ignore_schedule or self.schedule.is_open()

    def paused_reason(self) -> str | None:
        if not self.in_schedule():
            nxt = self.schedule.next_open()
            return "outside schedule" + (f" (opens {nxt:%a %H:%M})" if nxt else "")
        if self.ignore_schedule:
            return None
        if self.policy.get("yield_if_user_active", False):
            idle = self._idle_probe()
            if idle is not None and idle < self.idle_minutes * 60:
                return f"user active ({idle / 60:.0f} min idle < {self.idle_minutes:g})"
        g = self.gpu() if self.current_job is None else None
        if g and g["util_pct"] >= self.busy_gpu_util:
            return f"GPU busy ({g['util_pct']}% used by another program)"
        return None

    def health(self) -> dict[str, Any]:
        reason = self.paused_reason()
        return {"node_id": self.node_id, "version": __version__, "in_schedule": self.in_schedule(),
                "accepting": True, "paused_reason": reason, "running": self.current_job,
                "queue": self.queue.counts(), "gpu": self.gpu(), "schedule_tz": self.schedule.timezone}

    # ------------------------------------------------------------------ jobs
    def process_one(self) -> bool:
        """Run the oldest queued job (ignores the pause policy - callers check it). False if none."""
        job = self.queue.claim_next()
        if job is None:
            return False
        self.current_job = job["id"]
        try:
            runner = JOB_RUNNERS[job["type"]]
            out = runner(job, store=self.store, settings=self.settings, workspace=self.data_dir / "jobs" / job["id"],
                         is_cancelled=lambda: self.queue.is_cancelled(job["id"]),
                         on_stage=lambda s: self.queue.set_stage(job["id"], s), keep_workspace=self.keep_workspace)
        except Exception as e:  # a bug in the runner must not kill the worker loop
            log.exception("[worker] job %s crashed", job["id"])
            out = {"status": "failed", "exit_code": 1, "error": f"{type(e).__name__}: {e}", "result": None}
        finally:
            self.current_job = None
        self.queue.finish(job["id"], out["status"], result=out["result"], error=out["error"],
                          exit_code=out["exit_code"])
        log.info("[worker] job %s -> %s", job["id"], out["status"])
        return True

    def housekeeping(self) -> None:
        purged = self.queue.purge(self.retention_days)
        removed = self.store.gc(self.retention_days)
        if purged or removed:
            log.info("[worker] housekeeping: %d old jobs, %d unused blobs removed", purged, removed)

    def loop(self, stop: threading.Event) -> None:
        n = self.queue.requeue_running()
        if n:
            log.warning("[worker] %d interrupted job(s) re-queued", n)
        last_hk, last_reason = 0.0, None
        while not stop.is_set():
            try:
                if time.monotonic() - last_hk > 3600:
                    self.housekeeping()
                    last_hk = time.monotonic()
                reason = self.paused_reason()
                if reason != last_reason:
                    log.info("[worker] %s", f"paused: {reason}" if reason else "accepting work")
                    last_reason = reason
                busy = not reason and self.process_one()
            except Exception:  # keep serving; the next poll retries (e.g. data dir briefly unavailable)
                log.exception("[worker] loop error")
                busy = False
            if not busy:
                stop.wait(self.poll_sec)
