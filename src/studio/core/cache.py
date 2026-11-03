"""Content-addressed cache so identical TTS/LLM requests are never paid for (or waited on) twice."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .paths import atomic_replace


def cache_key(*parts: Any) -> str:
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def key_file(out: Path) -> Path:
    return out.with_name(out.name + ".key")


def build_cached(out: Path, key: str, build) -> bool:
    """Run `build()` (which writes `out`) unless `out` was already made from the same `key`.

    The key is stored in `<out>.key`; returns True when the existing file was reused.
    """
    kf = key_file(out)
    try:
        if out.is_file() and out.stat().st_size > 0 and kf.read_text(encoding="utf-8") == key:
            return True
    except OSError:
        pass
    kf.unlink(missing_ok=True)  # a failed build must never look valid
    build()
    kf.write_text(key, encoding="utf-8")
    return False


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class HashCache:
    """sha256 per (absolute path, size, mtime) so unchanged multi-GB clips are hashed once."""

    PRUNE_AT = 5000  # entries; stale ones (file gone) are dropped when the cache grows past this

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.dirty = False

    def sha(self, file: Path) -> str:
        st = file.stat()
        key = f"{file.resolve()}|{st.st_size}|{st.st_mtime_ns}"
        if key not in self.data:
            self.data[key] = file_sha256(file)
            self.dirty = True
        return self.data[key]

    def save(self) -> None:
        if not self.dirty:
            return
        if len(self.data) > self.PRUNE_AT:
            self.data = {k: v for k, v in self.data.items() if Path(k.rsplit("|", 2)[0]).exists()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        atomic_replace(tmp, self.path)
        self.dirty = False


class Cache:
    def __init__(self, root: Path, namespace: str):
        self.dir = root / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    def entry(self, key: str) -> Path:
        return self.dir / key

    def get_files(self, key: str, names: list[str]) -> list[Path] | None:
        d = self.entry(key)
        files = [d / n for n in names]
        return files if all(f.is_file() and f.stat().st_size > 0 for f in files) else None

    def put_files(self, key: str, files: dict[str, Path]) -> None:
        d = self.entry(key)
        d.mkdir(parents=True, exist_ok=True)
        for name, src in files.items():
            shutil.copy2(src, d / name)

    def get_json(self, key: str) -> Any | None:
        p = self.dir / f"{key}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def put_json(self, key: str, value: Any) -> None:
        (self.dir / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
