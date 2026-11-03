"""project.json schema (v2). v1 files from the original spec are upgraded on load."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "2.0"
SCENE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", validate_assignment=True)


class VisualSpec(_Model):
    """What is on screen for a scene.

    clip       - a video file (Flow/stock/own footage), fitted + trimmed/frozen to the scene length
    still      - an image animated with Ken Burns
    background - the project-level background (video loop, gradient or color)
    color      - a flat color (`color`)
    `overlay` is an optional PNG composited on top (e.g. the Reddit post card).
    Paths are project-relative, or `asset:<path>` relative to the repo assets/ folder.
    """

    type: Literal["clip", "still", "background", "color"] = "background"
    path: str | None = None
    fit_mode: Literal["crop", "pad"] | None = None
    ken_burns: Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "none"] = "zoom_in"
    color: str | None = None
    overlay: str | None = None
    overlay_until_sec: float | None = None  # show overlay only for the first N seconds of the scene


class Scene(_Model):
    scene_id: str
    narration: str = ""
    duration_sec: float | None = Field(default=None, gt=0, le=600)
    visual: VisualSpec = Field(default_factory=VisualSpec)
    audio_path: str | None = None
    subtitle_path: str | None = None
    image_prompt: str | None = None
    video_prompt: str | None = None
    source_note: str | None = None

    @field_validator("scene_id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not SCENE_ID_RE.match(v):
            raise ValueError("scene_id must be 1-64 chars of A-Z a-z 0-9 _ -")
        return v


class VideoSettings(_Model):
    format: str = "short_9x16"
    subtitle_mode: Literal["burn_in", "sidecar", "none"] = "burn_in"
    caption_style: str = "bold_pop"
    background: str = "gradient"  # gradient | color:#RRGGBB | asset:<path> | <project-relative path>
    transition: Literal["cut"] = "cut"


class AudioSettings(_Model):
    voice_profile: str | None = None  # id from voices/ registry; None -> registry default for language
    source: Literal["tts", "manual"] = "tts"
    volume: float = Field(default=1.0, ge=0, le=4)
    background_music: str | None = None
    music_volume_db: float = Field(default=-22, le=0)
    ducking: bool = True


class SourceInfo(_Model):
    type: Literal["manual", "url", "reddit", "threads", "none"] = "none"
    url: str | None = None
    platform: str | None = None
    community: str | None = None  # subreddit, etc.
    author: str | None = None
    title: str | None = None
    score: int | None = None
    fetched_at: str | None = None
    credit_text: str | None = None


class Budget(_Model):
    max_cost_usd: float = Field(default=0.0, ge=0)


class Project(_Model):
    schema_version: str = SCHEMA_VERSION
    project_id: str
    workflow: str = "ai_cinematic"
    title: str = ""
    language: Literal["vi", "en"] = "vi"
    platforms: list[str] = Field(default_factory=lambda: ["tiktok", "youtube_shorts"])
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    ai_generated: bool = True
    timing_mode: Literal["audio_driven", "fixed"] = "audio_driven"
    video: VideoSettings = Field(default_factory=VideoSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    source: SourceInfo = Field(default_factory=SourceInfo)
    budget: Budget = Field(default_factory=Budget)
    options: dict[str, Any] = Field(default_factory=dict)  # workflow-specific knobs
    scenes: list[Scene] = Field(default_factory=list)

    @field_validator("project_id")
    @classmethod
    def _check_pid(cls, v: str) -> str:
        if not SCENE_ID_RE.match(v):
            raise ValueError("project_id must be 1-64 chars of A-Z a-z 0-9 _ -")
        return v

    @model_validator(mode="before")
    @classmethod
    def _upgrade_v1(cls, data: Any) -> Any:
        return upgrade_v1(data) if isinstance(data, dict) and _looks_v1(data) else data

    @model_validator(mode="after")
    def _check_scenes(self) -> Project:
        seen: set[str] = set()
        for s in self.scenes:
            if s.scene_id in seen:
                raise ValueError(f"duplicate scene_id: {s.scene_id}")
            seen.add(s.scene_id)
            if self.timing_mode == "fixed" and s.duration_sec is None:
                raise ValueError(f"{s.scene_id}: duration_sec is required when timing_mode is 'fixed'")
        return self

    def scene(self, scene_id: str) -> Scene:
        for s in self.scenes:
            if s.scene_id == scene_id:
                return s
        raise KeyError(scene_id)


def _looks_v1(data: dict[str, Any]) -> bool:
    version = str(data.get("schema_version", ""))
    if version:
        return version.startswith("1")
    video, audio = data.get("video") or {}, data.get("audio") or {}
    return ("width" in video or "voice" in audio
            or any("video_path" in s or "image_path" in s for s in data.get("scenes", []) if isinstance(s, dict)))


def upgrade_v1(data: dict[str, Any]) -> dict[str, Any]:
    """Map the original spec's v1.0 layout onto v2 (fixed timing, clip visuals)."""
    d = dict(data)
    d["schema_version"] = SCHEMA_VERSION
    d.setdefault("workflow", "ai_cinematic")
    d.setdefault("timing_mode", "fixed")
    lang = str(d.get("language", "vi"))
    d["language"] = "en" if lang.lower().startswith("en") else "vi"
    v1_video = d.get("video") or {}
    w, h = v1_video.get("width", 1080), v1_video.get("height", 1920)
    fmt = "short_9x16" if h > w else ("square_1x1" if h == w else "long_16x9")
    d["video"] = {
        "format": fmt,
        "subtitle_mode": "burn_in" if v1_video.get("subtitle_mode", "burn_in") == "burn_in" else "sidecar",
    }
    a1 = d.get("audio") or {}
    d["audio"] = {
        "source": "manual" if a1.get("source") == "manual" else "tts",
        "volume": a1.get("volume", 1.0),
        "background_music": a1.get("background_music"),
        "music_volume_db": a1.get("music_volume_db", -22),
    }
    if a1.get("voice"):
        d["options"] = {**d.get("options", {}), "v1_edge_voice": a1["voice"]}
    scenes = []
    for s in d.get("scenes", []):
        s = dict(s)
        vpath, ipath = s.pop("video_path", None), s.pop("image_path", None)
        if "visual" not in s:
            if vpath:
                s["visual"] = {"type": "clip", "path": vpath}
            elif ipath:
                s["visual"] = {"type": "still", "path": ipath}
        scenes.append(s)
    d["scenes"] = scenes
    return d
