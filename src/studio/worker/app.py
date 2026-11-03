"""HTTP API of the worker (FastAPI). Every endpoint requires `Authorization: Bearer <token>`.

There is no endpoint that runs arbitrary commands: a job is one of the predefined types in JOB_RUNNERS
with a strictly validated request (unknown fields, stages or unsafe paths are rejected with 422).
"""

from __future__ import annotations

import hmac
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.paths import is_safe_relative
from .jobs import REMOTE_STAGES
from .service import WorkerService
from .store import SHA_RE, BlobError

Sha = Annotated[str, Field(pattern=SHA_RE.pattern)]
StageName = Literal[REMOTE_STAGES]  # type: ignore[valid-type]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileRef(_Strict):
    path: str = Field(min_length=1, max_length=400)
    sha256: Sha
    size: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def _safe(cls, v: str) -> str:
        if "\\" in v or not is_safe_relative(v):
            raise ValueError("path must be relative, '/'-separated and stay inside the project")
        return v


class JobOptions(_Strict):
    overwrite: bool = False
    strict: bool = False
    allow_sidecar: bool = False
    burn_subs: bool | None = None


class JobRequest(_Strict):
    type: Literal["pipeline"]
    project_id: str = Field(pattern=r"^[A-Za-z0-9_\-]{1,80}$")
    stages: list[StageName] = Field(min_length=1, max_length=len(REMOTE_STAGES))
    files: list[FileRef] = Field(min_length=1, max_length=20000)
    assets: list[FileRef] = Field(default_factory=list, max_length=2000)
    options: JobOptions = Field(default_factory=JobOptions)
    client: str | None = Field(default=None, max_length=64)


class MissingRequest(_Strict):
    sha256: list[Sha] = Field(max_length=25000)


def create_app(service: WorkerService) -> FastAPI:
    app = FastAPI(title="studio-worker", docs_url=None, redoc_url=None, openapi_url=None)
    expected = f"Bearer {service.token}".encode()

    def auth(request: Request) -> None:
        got = request.headers.get("authorization", "").encode()
        if not hmac.compare_digest(got, expected):
            raise HTTPException(401, "missing or wrong token", headers={"WWW-Authenticate": "Bearer"})

    def blob_http(e: BlobError) -> HTTPException:
        return HTTPException(e.status, str(e))

    @app.get("/v1/health", dependencies=[Depends(auth)])
    def health() -> dict:
        return service.health()

    @app.post("/v1/blobs/missing", dependencies=[Depends(auth)])
    def blobs_missing(body: MissingRequest) -> dict:
        return {"missing": service.store.missing(body.sha256)}

    @app.put("/v1/blobs/{sha}", dependencies=[Depends(auth)])
    async def blob_put(sha: str, request: Request) -> dict:
        try:
            if service.store.has(sha):
                service.store.touch(sha)
                return {"sha256": sha, "stored": False}
            size = await service.store.put_stream(sha, request.stream())
        except BlobError as e:
            raise blob_http(e) from e
        return {"sha256": sha, "stored": True, "size": size}

    @app.get("/v1/blobs/{sha}", dependencies=[Depends(auth)])
    def blob_get(sha: str) -> FileResponse:
        try:
            path = service.store.path(sha)
        except BlobError as e:
            raise blob_http(e) from e
        if not path.is_file():
            raise HTTPException(404, "no such blob")
        service.store.touch(sha)
        return FileResponse(path, media_type="application/octet-stream")

    @app.post("/v1/jobs", dependencies=[Depends(auth)], status_code=201)
    def job_submit(body: JobRequest) -> dict:
        missing = service.store.missing([f.sha256 for f in (*body.files, *body.assets)])
        if missing:
            raise HTTPException(409, {"message": "upload these blobs first", "missing": missing})
        job_id = service.queue.add(body.type, body.model_dump())
        return {"id": job_id, "status": "queued", "paused_reason": service.paused_reason()}

    @app.get("/v1/jobs", dependencies=[Depends(auth)])
    def job_list(limit: int = 50) -> dict:
        return {"jobs": service.queue.list(max(1, min(limit, 500)))}

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(auth)])
    def job_get(job_id: str) -> dict:
        job = service.queue.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        return job

    @app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(auth)])
    def job_cancel(job_id: str) -> dict:
        status = service.queue.cancel(job_id)
        if status is None:
            raise HTTPException(404, "no such job")
        return {"id": job_id, "status": status}

    return app
