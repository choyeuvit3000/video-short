"""Topic packs (workflows/_shared/topics/<id>.yaml): tone, writing rules, allowed Manim templates, palette,
fact-check policy, disclaimers and project option defaults (backdrop, scene_count...) for one knowledge subject.
Add a topic by adding a YAML file."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..core.config import Settings, load_yaml
from ..core.errors import ValidationError as StudioValidationError


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: dict[str, str]
    tone: str = ""
    guidance: str = ""
    templates: list[str] = Field(min_length=1)
    palette: dict | None = None
    caption_style: str | None = None
    review_required: bool = True
    require_sources: bool = True
    disclaimer: dict[str, str] | None = None
    disclaimer_on_screen: bool = False
    forbidden: list[str] = Field(default_factory=list)
    hashtags: dict[str, list[str]] = Field(default_factory=dict)
    example_briefs: list[str] = Field(default_factory=list)
    # project option defaults over the workflow's (a --set on `studio new` still wins), e.g. backdrop: stars
    options: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Topic:
        from ..renderers.manim_render import BACKDROPS, TEMPLATES

        unknown = [t for t in self.templates if t not in TEMPLATES]
        if unknown:
            raise ValueError(f"unknown manim template(s): {', '.join(unknown)}")
        if self.disclaimer is not None and not {"vi", "en"} <= set(self.disclaimer):
            raise ValueError("disclaimer needs both vi and en")
        if self.options.get("backdrop", "none") not in BACKDROPS:
            raise ValueError(f"options.backdrop must be one of: {', '.join(BACKDROPS)}")
        return self

    def label(self, lang: str) -> str:
        return self.name.get(lang) or self.name.get("en") or self.id

    def disclaimer_for(self, lang: str) -> str | None:
        return (self.disclaimer or {}).get(lang)


def topics_dir(settings: Settings) -> Path:
    return settings.path("workflows") / "_shared" / "topics"


def load_topic(settings: Settings, topic_id: str) -> Topic:
    path = topics_dir(settings) / f"{topic_id}.yaml"
    if not path.is_file():
        known = ", ".join(p.stem for p in sorted(topics_dir(settings).glob("*.yaml")))
        raise StudioValidationError(f"unknown topic '{topic_id}' (known: {known})", code="unknown_topic")
    data = load_yaml(path)
    try:
        topic = Topic.model_validate(data)
    except ValidationError as e:
        raise StudioValidationError(f"topic pack {path.name}: {e}", code="bad_topic") from None
    if topic.id != path.stem:
        raise StudioValidationError(f"topic pack {path.name}: id '{topic.id}' must match the file name",
                                    code="bad_topic")
    return topic


def list_topics(settings: Settings) -> list[Topic]:
    return [load_topic(settings, p.stem) for p in sorted(topics_dir(settings).glob("*.yaml"))]
