"""HTTP client for a studio-worker node (used by the controller)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..core.errors import StudioError

CHUNK = 1024 * 1024


class NodeError(StudioError):
    pass


class NodeClient:
    def __init__(self, http: httpx.Client, node_id: str, token: str):
        self.http = http
        self.node_id = node_id
        self.http.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def for_node(cls, node, *, timeout: float = 30.0) -> NodeClient:
        if not node.url or not node.token:
            raise NodeError(f"node '{node.id}' has no url or token", code="node_unavailable")
        http = httpx.Client(base_url=node.url.rstrip("/"),
                            timeout=httpx.Timeout(timeout, read=max(timeout, 300.0)))
        return cls(http, node.id, node.token)

    def _req(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = self.http.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise NodeError(f"node '{self.node_id}' unreachable: {type(e).__name__}: {e}",
                            code="node_offline") from e
        if r.status_code == 401:
            raise NodeError(f"node '{self.node_id}' rejected the token (check .env on both machines)",
                            code="node_auth")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:300]
            raise NodeError(f"node '{self.node_id}' {method} {url} -> {r.status_code}: {detail}", code="node_http")
        return r

    def health(self) -> dict[str, Any]:
        return self._req("GET", "/v1/health").json()

    def missing(self, shas: list[str]) -> list[str]:
        if not shas:
            return []
        return self._req("POST", "/v1/blobs/missing", json={"sha256": sorted(set(shas))}).json()["missing"]

    def upload(self, sha: str, path: Path) -> None:
        def chunks():
            with path.open("rb") as f:
                while chunk := f.read(CHUNK):
                    yield chunk

        self._req("PUT", f"/v1/blobs/{sha}", content=chunks(),
                  headers={"Content-Type": "application/octet-stream"})

    def download(self, sha: str, dest: Path) -> None:
        try:
            with self.http.stream("GET", f"/v1/blobs/{sha}") as r:
                if r.status_code != 200:
                    raise NodeError(f"node '{self.node_id}' blob {sha[:12]} -> {r.status_code}", code="node_http")
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes(CHUNK):
                        f.write(chunk)
        except httpx.HTTPError as e:
            raise NodeError(f"node '{self.node_id}' download failed: {e}", code="node_offline") from e

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._req("POST", "/v1/jobs", json=request).json()

    def job(self, job_id: str) -> dict[str, Any]:
        return self._req("GET", f"/v1/jobs/{job_id}").json()

    def jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._req("GET", "/v1/jobs", params={"limit": limit}).json()["jobs"]

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self._req("POST", f"/v1/jobs/{job_id}/cancel").json()
