"""Shared fixtures. Tests never touch the network, real voices or the repo's cache/ and projects/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.core.config import Settings, deep_merge, get_settings
from studio.core.errors import ToolMissingError
from studio.core.ffmpeg import ffmpeg_bin, run_ffmpeg
from studio.core.project import ProjectContext, scaffold
from studio.core.schema import Project


def _has_ffmpeg() -> bool:
    try:
        ffmpeg_bin()
        return True
    except ToolMissingError:
        return False


HAS_FFMPEG = _has_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not found (set STUDIO_FFMPEG_DIR)")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Repo config with cache in tmp and offline-only providers."""
    base = get_settings()
    data = deep_merge(base.data, {
        "paths": {"cache": str(tmp_path / "_cache"), "output": None},
        "providers": {"llm": ["manual"], "align": ["provider_words", "estimate"]},
        # a worker PC's config/local.yaml (worker.node_id: home-gpu + its token in .env) must not leak in
        "worker": {"node_id": None},
        "planning": {"required": False},
        "reviews": {"required": False},
    })
    data.pop("voice_defaults", None)  # a GPU PC's local default voice (VieNeu) must not leak in either
    return Settings(root=base.root, data=data, formats=base.formats)


def make_project(project_dir: Path, settings: Settings, **fields) -> ProjectContext:
    data = deep_merge({"project_id": "test_project", "language": "vi", "video": {"format": "test_9x16"},
                       "audio": {"voice_profile": "mock-vi"}}, fields)
    scaffold(project_dir, Project.model_validate(data))
    return ProjectContext(project_dir, settings=settings)


def color_clip(path: Path, color: str, seconds: float, size: str = "360x640", fps: int = 30) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # hue rotates over the clip so it is not a frozen picture for QC
    run_ffmpeg(["-f", "lavfi", "-i", f"color=c={color}:s={size}:r={fps}:d={seconds},hue=H=2*PI*t/{seconds}",
                "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], stage="fixture")
    return path


def color_image(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (800, 600)) -> Path:
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).rectangle([size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4], fill=(255, 255, 255))
    im.save(path)
    return path


def three_scene_fixed(project_dir: Path, settings: Settings) -> ProjectContext:
    """The spec's 3-scene fixture: three 8s clips, Vietnamese narration, fixed timing."""
    ctx = make_project(project_dir, settings, timing_mode="fixed", workflow="ai_cinematic",
                       video={"background": "color:#000000"})
    for i, c in enumerate(("red", "green", "blue"), start=1):
        color_clip(project_dir / "clips" / f"scene_{i:02d}.mp4", c, 8)
    ctx.project.scenes = [
        {"scene_id": f"scene_{i:02d}", "duration_sec": 8, "narration": n,
         "visual": {"type": "clip", "path": f"clips/scene_{i:02d}.mp4"}}
        for i, n in enumerate(["Cảnh một: bầu trời đỏ rực.", "Cảnh hai: cánh đồng xanh mướt.",
                               "Cảnh ba: biển xanh thẳm."], start=1)
    ]
    ctx.project = Project.model_validate(json.loads(ctx.project.model_dump_json()))
    ctx.save()
    return ctx
