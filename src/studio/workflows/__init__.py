"""Workflow recipes. The recipe (stages, defaults, prompts) is data in workflows/<name>/workflow.yaml;
the stage functions live in this package and are looked up by name."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.config import Settings, deep_merge, load_yaml
from ..core.errors import ValidationError
from ..core.project import ProjectContext

StageFn = Callable[[ProjectContext, dict], str]

DEFAULT_STAGES = ["validate", "voice", "render", "qc", "package"]


def workflow_dir(settings: Settings, name: str) -> Path:
    return settings.path("workflows") / name


def load_workflow(settings: Settings, name: str) -> dict[str, Any]:
    path = workflow_dir(settings, name) / "workflow.yaml"
    if not path.is_file():
        raise ValidationError(f"unknown workflow '{name}' (no {path})", code="unknown_workflow")
    wf = load_yaml(path)
    wf.setdefault("name", name)
    wf.setdefault("stages", DEFAULT_STAGES)
    wf.setdefault("status", "planned")
    return wf


def list_workflows(settings: Settings) -> list[dict[str, Any]]:
    root = settings.path("workflows")
    return [load_workflow(settings, p.parent.name) for p in sorted(root.glob("*/workflow.yaml"))]


def project_defaults(wf: dict[str, Any], fmt: str) -> dict[str, Any]:
    """Project fields for a new project: workflow defaults + per-format overrides."""
    base = dict(wf.get("defaults") or {})
    over = (wf.get("format_overrides") or {}).get(fmt) or {}
    return deep_merge(base, over)


def read_prompt(settings: Settings, workflow: str, name: str) -> str:
    for d in (workflow_dir(settings, workflow) / "prompts", settings.path("workflows") / "_shared" / "prompts"):
        p = d / name
        if p.is_file():
            return p.read_text(encoding="utf-8")
    raise ValidationError(f"prompt template '{name}' not found for workflow {workflow}", code="missing_prompt")


def fill(template: str, values: dict[str, Any]) -> str:
    """{{key}} placeholders (single braces stay literal so JSON examples in prompts are safe)."""
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def get_stages() -> dict[str, StageFn]:
    from . import ai_cinematic, story_reader
    from .common import COMMON_STAGES

    return {**COMMON_STAGES, **story_reader.STAGES, **ai_cinematic.STAGES}
