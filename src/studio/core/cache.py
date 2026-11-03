"""Content-addressed cache so identical TTS/LLM requests are never paid for (or waited on) twice."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def cache_key(*parts: Any) -> str:
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


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
