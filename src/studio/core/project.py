"""Project folder handling: load/save project.json, stage state, media path resolution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .config import Settings, get_settings
from .errors import ValidationError
from .paths import resolve_inside
from .schema import Project

PROJECT_SUBDIRS = ("source", "images", "clips", "audio", "subtitles", "music", "work", "output", "logs")


class ProjectContext:
    def __init__(self, project_dir: Path, settings: Settings | None = None):
        self.dir = project_dir.resolve()
        self.settings = settings or get_settings()
        self.project = load_project(self.dir / "project.json")

    # ---------------------------------------------------------------- persistence
    def save(self) -> None:
        save_project(self.dir / "project.json", self.project)

    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    def state(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"stages": {}}

    def set_stage(self, stage: str, status: str, message: str = "") -> None:
        st = self.state()
        st.setdefault("stages", {})[stage] = {
            "status": status,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "message": message,
        }
        self.state_path.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

    def stage_status(self, stage: str) -> str:
        return self.state().get("stages", {}).get(stage, {}).get("status", "pending")

    # ---------------------------------------------------------------- paths
    @property
    def fmt(self):
        return self.settings.format(self.project.video.format)

    @property
    def work(self) -> Path:
        p = self.dir / "work"
        p.mkdir(exist_ok=True)
        return p

    @property
    def output(self) -> Path:
        p = self.dir / "output"
        p.mkdir(exist_ok=True)
        return p

    def resolve(self, ref: str, *, what: str = "path") -> Path:
        """`asset:<path>` -> repo assets folder; otherwise project-relative. Never escapes either root."""
        if ref.startswith("asset:"):
            rel = ref[len("asset:"):]
            overlay = self.settings.get("paths.asset_overlay")
            if overlay:  # worker jobs: assets uploaded with the job win over the node's own library
                p = resolve_inside(Path(overlay), rel, what=what)
                if p.exists():
                    return p
            return resolve_inside(self.settings.path("assets"), rel, what=what)
        return resolve_inside(self.dir, ref, what=what)

    def asset_dir(self, rel: str) -> Path:
        """An assets sub-folder, preferring the job overlay when it has files."""
        overlay = self.settings.get("paths.asset_overlay")
        if overlay:
            p = resolve_inside(Path(overlay), rel, what="asset folder")
            if p.is_dir() and any(p.iterdir()):
                return p
        return resolve_inside(self.settings.path("assets"), rel, what="asset folder")

    def timeline_path(self) -> Path:
        return self.work / "timeline.json"

    def load_timeline(self) -> dict[str, Any]:
        p = self.timeline_path()
        if not p.exists():
            raise ValidationError("No timeline yet - run the voice stage first", code="no_timeline")
        return json.loads(p.read_text(encoding="utf-8"))


def load_project(path: Path) -> Project:
    if not path.is_file():
        raise ValidationError(f"project.json not found: {path}", code="missing_project")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise ValidationError(f"project.json is not valid JSON: {e}", code="schema_error") from e
    try:
        return Project.model_validate(raw)
    except PydanticValidationError as e:
        msgs = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
        raise ValidationError(f"project.json schema error: {msgs}", code="schema_error") from e


def save_project(path: Path, project: Project) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(project.model_dump_json(indent=2, exclude_none=False), encoding="utf-8")
    tmp.replace(path)


def scaffold(project_dir: Path, project: Project, *, force: bool = False) -> None:
    if (project_dir / "project.json").exists() and not force:
        raise ValidationError(f"Project already exists: {project_dir}", code="project_exists")
    project_dir.mkdir(parents=True, exist_ok=True)
    for d in PROJECT_SUBDIRS:
        (project_dir / d).mkdir(exist_ok=True)
    save_project(project_dir / "project.json", project)
