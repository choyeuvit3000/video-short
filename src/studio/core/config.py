"""Load config/studio.yaml (+ machine-local config/local.yaml), formats and .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .errors import ValidationError
from .paths import find_repo_root


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValidationError(f"{path} must contain a mapping", code="config_error")
    return data


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, does not override variables already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class FormatProfile:
    name: str
    width: int
    height: int
    fps: int
    max_duration_sec: float
    caption: dict[str, Any]
    safe_zone: dict[str, int]

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width


@dataclass
class Settings:
    root: Path
    data: dict[str, Any]
    formats: dict[str, FormatProfile]

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def path(self, key: str) -> Path:
        return self.root / self.get(f"paths.{key}", key)

    def format(self, name: str) -> FormatProfile:
        if name not in self.formats:
            raise ValidationError(
                f"Unknown format '{name}'. Available: {', '.join(sorted(self.formats))}", code="schema_error"
            )
        return self.formats[name]


@lru_cache(maxsize=4)
def _load(root_str: str) -> Settings:
    root = Path(root_str)
    load_dotenv(root / ".env")
    data = load_yaml(root / "config" / "studio.yaml")
    data = deep_merge(data, load_yaml(root / "config" / "local.yaml"))
    fmt_raw = load_yaml(root / "config" / "formats.yaml").get("formats", {})
    formats = {
        name: FormatProfile(
            name=name,
            width=int(v["width"]),
            height=int(v["height"]),
            fps=int(v.get("fps", 30)),
            max_duration_sec=float(v.get("max_duration_sec", 600)),
            caption=dict(v.get("caption", {})),
            safe_zone=dict(v.get("safe_zone", {})),
        )
        for name, v in fmt_raw.items()
    }
    return Settings(root=root, data=data, formats=formats)


def get_settings(root: Path | None = None) -> Settings:
    return _load(str((root or find_repo_root()).resolve()))
