"""SQLite job queue on the worker. Jobs survive restarts; a job left `running` by a crash is re-queued."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUSES = ("queued", "running", "done", "failed", "cancelled")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    project_id TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    request TEXT NOT NULL,
    result TEXT,
    error TEXT,
    exit_code INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    cancel INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class JobQueue:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """One short connection per call (thread-safe with the lock, and never holds the file open)."""
        with self._lock:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            try:
                yield c
                c.commit()
            finally:
                c.close()

    def _exec(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._db() as c:
            return c.execute(sql, args).fetchall()

    @staticmethod
    def _row(r: sqlite3.Row | None, *, full: bool = True) -> dict[str, Any] | None:
        if r is None:
            return None
        d = dict(r)
        d["cancel"] = bool(d["cancel"])
        req = json.loads(d.pop("request"))
        res = d.pop("result")
        d["stages"] = req.get("stages", [])
        if full:
            d["request"] = req
            d["result"] = json.loads(res) if res else None
        return d

    def add(self, job_type: str, request: dict[str, Any]) -> str:
        job_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self._exec("INSERT INTO jobs(id, type, status, project_id, created_at, request) VALUES (?,?,?,?,?,?)",
                   (job_id, job_type, "queued", request.get("project_id"), _now(),
                    json.dumps(request, ensure_ascii=False)))
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        rows = self._exec("SELECT * FROM jobs WHERE id=?", (job_id,))
        return self._row(rows[0] if rows else None)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))
        return [self._row(r, full=False) for r in rows]

    def counts(self) -> dict[str, int]:
        rows = self._exec("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        out = dict.fromkeys(STATUSES, 0)
        out.update({r["status"]: r["n"] for r in rows})
        return out

    def claim_next(self) -> dict[str, Any] | None:
        """Atomically move the oldest queued job to running."""
        with self._db() as c:
            r = c.execute("SELECT id FROM jobs WHERE status='queued' AND cancel=0 "
                          "ORDER BY created_at, id LIMIT 1").fetchone()
            if r is None:
                return None
            c.execute("UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
                      (_now(), r["id"]))
        return self.get(r["id"])

    def set_stage(self, job_id: str, stage: str) -> None:
        self._exec("UPDATE jobs SET stage=? WHERE id=?", (stage, job_id))

    def finish(self, job_id: str, status: str, *, result: dict | None = None, error: str | None = None,
               exit_code: int | None = None) -> None:
        assert status in STATUSES
        self._exec("UPDATE jobs SET status=?, finished_at=?, result=?, error=?, exit_code=? WHERE id=?",
                   (status, _now(), json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error, exit_code, job_id))

    def cancel(self, job_id: str) -> str | None:
        """Queued -> cancelled now; running -> flagged (stops before its next stage). Returns new status."""
        with self._db() as c:
            r = c.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if r is None:
                return None
            if r["status"] == "queued":
                c.execute("UPDATE jobs SET status='cancelled', cancel=1, finished_at=? WHERE id=?", (_now(), job_id))
                return "cancelled"
            if r["status"] == "running":
                c.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job_id,))
                return "cancelling"
            return r["status"]

    def is_cancelled(self, job_id: str) -> bool:
        rows = self._exec("SELECT cancel FROM jobs WHERE id=?", (job_id,))
        return bool(rows and rows[0]["cancel"])

    def requeue_running(self) -> int:
        """Called at startup: a job still `running` was interrupted (crash, reboot, schedule end)."""
        with self._db() as c:
            return c.execute("UPDATE jobs SET status='queued', stage=NULL WHERE status='running'").rowcount

    def purge(self, older_than_days: float) -> int:
        cutoff = datetime.fromtimestamp(datetime.now(UTC).timestamp() - older_than_days * 86400, UTC)
        with self._db() as c:
            return c.execute("DELETE FROM jobs WHERE status IN ('done','failed','cancelled') AND finished_at < ?",
                             (cutoff.isoformat(timespec="seconds"),)).rowcount
