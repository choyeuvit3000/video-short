"""Repository root discovery and safe path handling."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import ValidationError

_MARKERS = ("pyproject.toml", "config/studio.yaml")


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the studio repository (env STUDIO_HOME wins, then walk up from cwd, then package location)."""
    env = os.environ.get("STUDIO_HOME")
    if env:
        return Path(env).resolve()
    candidates = []
    here = (start or Path.cwd()).resolve()
    candidates.extend([here, *here.parents])
    pkg = Path(__file__).resolve()
    candidates.extend(pkg.parents)
    for c in candidates:
        if all((c / m).exists() for m in _MARKERS):
            return c
    raise ValidationError("Cannot find the studio repository root (config/studio.yaml)", code="no_repo")


def resolve_inside(root: Path, rel: str | os.PathLike[str], *, what: str = "path") -> Path:
    """Resolve `rel` against `root`, refusing absolute paths and anything escaping the root."""
    p = Path(rel)
    if p.is_absolute() or p.drive or p.root:
        raise ValidationError(f"{what} must be relative to the project: {rel}", code="path_absolute")
    resolved = (root / p).resolve()
    root_r = root.resolve()
    if resolved != root_r and root_r not in resolved.parents:
        raise ValidationError(f"{what} escapes the project folder: {rel}", code="path_traversal")
    return resolved


def is_safe_relative(rel: str) -> bool:
    p = Path(rel)
    if p.is_absolute() or p.drive or p.root:
        return False
    return ".." not in p.parts


def atomic_replace(tmp: Path, final: Path) -> None:
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, final)
