"""Content-addressed blob store on the worker: <data_dir>/blobs/ab/<sha256>."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
import uuid
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class BlobError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class BlobStore:
    def __init__(self, root: Path, max_bytes: int):
        self.root = root
        self.max_bytes = max_bytes
        (root / "tmp").mkdir(parents=True, exist_ok=True)

    def path(self, sha: str) -> Path:
        if not SHA_RE.match(sha):
            raise BlobError("bad sha256")
        return self.root / sha[:2] / sha

    def has(self, sha: str) -> bool:
        return self.path(sha).is_file()

    def touch(self, sha: str) -> None:
        p = self.path(sha)
        if p.is_file():
            os.utime(p)

    def missing(self, shas: list[str]) -> list[str]:
        return sorted({s for s in shas if not self.has(s)})

    def new_tmp(self) -> Path:
        return self.root / "tmp" / f"{uuid.uuid4().hex}.part"

    def commit(self, tmp: Path, sha: str, actual: str) -> Path:
        if actual != sha:
            tmp.unlink(missing_ok=True)
            raise BlobError(f"sha256 mismatch: expected {sha}, got {actual}")
        dest = self.path(sha)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
        return dest

    async def put_stream(self, sha: str, chunks) -> int:
        """Stream an upload to a temp file while hashing; only a verified blob is kept."""
        self.path(sha)  # validates the name
        tmp, h, size = self.new_tmp(), hashlib.sha256(), 0
        try:
            with tmp.open("wb") as f:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise BlobError(f"upload larger than worker.max_upload_gb ({self.max_bytes} bytes)", 413)
                    h.update(chunk)
                    f.write(chunk)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        self.commit(tmp, sha, h.hexdigest())
        return size

    def put_file(self, src: Path) -> tuple[str, int]:
        """Add a local file (job results); returns (sha, size)."""
        tmp, h = self.new_tmp(), hashlib.sha256()
        with src.open("rb") as fi, tmp.open("wb") as fo:
            while chunk := fi.read(1024 * 1024):
                h.update(chunk)
                fo.write(chunk)
        sha = h.hexdigest()
        if self.has(sha):
            tmp.unlink()
            self.touch(sha)
        else:
            self.commit(tmp, sha, sha)
        return sha, src.stat().st_size

    def copy_to(self, sha: str, dest: Path) -> None:
        src = self.path(sha)
        if not src.is_file():
            raise BlobError(f"blob {sha} not on this worker", 409)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        self.touch(sha)

    def gc(self, days: float) -> int:
        """Delete blobs not used for `days` (mtime is bumped on every use) and stale temp files."""
        cutoff = time.time() - days * 86400
        n = 0
        for p in self.root.glob("*/*"):
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                n += 1
        return n
