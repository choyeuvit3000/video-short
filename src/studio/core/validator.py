"""Pre-render validation: paths, missing media, durations. Returns categorized issues per scene."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import StudioError
from .media_probe import probe
from .paths import is_safe_relative
from .project import ProjectContext


@dataclass
class Issue:
    level: str  # error | warning
    code: str
    message: str
    scene_id: str | None = None

    def __str__(self) -> str:
        sid = f"[{self.scene_id}] " if self.scene_id else ""
        return f"{self.level.upper():7} {self.code:18} {sid}{self.message}"


def _check_ref(ctx: ProjectContext, ref: str, issues: list[Issue], *, code: str, scene_id: str | None,
               what: str) -> bool:
    body = ref[len("asset:"):] if ref.startswith("asset:") else ref
    if not is_safe_relative(body):
        issues.append(Issue("error", "path_traversal", f"{what} must be relative and inside the folder: {ref}",
                            scene_id))
        return False
    try:
        p = ctx.resolve(ref, what=what)
    except StudioError as e:
        issues.append(Issue("error", e.code, str(e), scene_id))
        return False
    if not p.is_file():
        issues.append(Issue("error", code, f"{what} not found: {ref}", scene_id))
        return False
    return True


def _check_manim(ctx: ProjectContext, scene_id: str, v, issues: list[Issue]) -> None:
    from ..renderers.manim_render import manim_available, photo_path, validate_params

    if not manim_available():
        issues.append(Issue("error", "manim_missing", 'manim is not installed - uv pip install -e ".[manim]"',
                            scene_id))
    if v.file:
        if not v.file.endswith(".py") or not v.scene_class:
            issues.append(Issue("error", "bad_manim_params", "custom manim scene needs file: <name>.py and "
                                "scene_class", scene_id))
        elif _check_ref(ctx, v.file, issues, code="missing_manim_file", scene_id=scene_id, what="manim file"):
            issues.append(Issue("warning", "custom_code", f"{v.file} is Python that runs on this machine - "
                                "render only files you wrote or reviewed", scene_id))
    elif not v.template:
        issues.append(Issue("error", "schema_error", "visual.type=manim needs a template (or file + scene_class)",
                            scene_id))
    else:
        try:
            params = validate_params(v.template, v.params)
            if v.template == "photo":
                photo_path(ctx, params, scene_id)
        except StudioError as e:
            issues.append(Issue("error", e.code, str(e), scene_id))


def validate_project(ctx: ProjectContext, *, require_media: bool = True, require_audio: bool = False) -> list[Issue]:
    p = ctx.project
    issues: list[Issue] = []
    try:
        fmt = ctx.fmt
    except StudioError as e:
        return [Issue("error", e.code, str(e))]
    if not p.scenes:
        issues.append(Issue("error", "no_scenes", "project has no scenes"))
    bg = p.video.background
    if bg not in ("gradient", "auto") and not bg.startswith("color:"):
        _check_ref(ctx, bg, issues, code="missing_background", scene_id=None, what="background")
    if p.audio.background_music:
        _check_ref(ctx, p.audio.background_music, issues, code="missing_music", scene_id=None, what="music")

    total = 0.0
    for s in p.scenes:
        v = s.visual
        if s.duration_sec:
            total += s.duration_sec
        if v.type in ("clip", "still"):
            if not v.path:
                issues.append(Issue("error", "schema_error", f"visual.type={v.type} needs visual.path", s.scene_id))
            elif require_media and _check_ref(
                ctx, v.path, issues, code="missing_clip" if v.type == "clip" else "missing_image",
                scene_id=s.scene_id, what=f"{v.type} file",
            ) and v.type == "clip":
                try:
                    info = probe(ctx.resolve(v.path))
                    if not info.has_video:
                        issues.append(Issue("error", "bad_clip", "file has no video stream", s.scene_id))
                    else:
                        if abs(info.width / max(info.height, 1) - fmt.width / fmt.height) > 0.02:
                            issues.append(Issue("warning", "aspect_mismatch",
                                                f"{info.width}x{info.height} will be {v.fit_mode or 'crop'}-fitted "
                                                f"to {fmt.width}x{fmt.height}", s.scene_id))
                        if s.duration_sec and info.duration + 0.05 < s.duration_sec:
                            issues.append(Issue("warning", "clip_short",
                                                f"clip {info.duration:.2f}s < scene {s.duration_sec:.2f}s - "
                                                "last frame will be frozen", s.scene_id))
                except StudioError as e:
                    issues.append(Issue("error", e.code, str(e), s.scene_id))
        if v.type == "manim":
            _check_manim(ctx, s.scene_id, v, issues)
        if v.overlay:
            _check_ref(ctx, v.overlay, issues, code="missing_overlay", scene_id=s.scene_id, what="overlay")
        if p.audio.source == "manual" or require_audio:
            if s.narration.strip() and not s.audio_path:
                issues.append(Issue("error", "missing_audio", "narration present but no audio_path", s.scene_id))
            elif s.audio_path:
                _check_ref(ctx, s.audio_path, issues, code="missing_audio", scene_id=s.scene_id, what="audio")
        if s.subtitle_path:
            _check_ref(ctx, s.subtitle_path, issues, code="missing_subtitle", scene_id=s.scene_id, what="subtitle")
    if p.timing_mode == "fixed" and total > fmt.max_duration_sec:
        issues.append(Issue("warning", "too_long", f"total {total:.1f}s > {fmt.max_duration_sec:.0f}s for {fmt.name}"))
    return issues
