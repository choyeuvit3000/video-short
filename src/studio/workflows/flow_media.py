"""Technical checks for imported clips; these do not establish AI provenance or art quality."""

from __future__ import annotations

import hashlib
import math
from fractions import Fraction

from ..core.errors import StudioError
from ..core.media_probe import probe
from ..core.project import ProjectContext
from ..core.schema import Scene


def check_imported_clip(ctx: ProjectContext, scene: Scene) -> str | None:
    """Return a repair instruction instead of silently freezing a short/broken clip.

    Opt-in via strict_clip_validation so stock/manual projects retain their existing
    crop/pad/last-frame policy. Prefer VIDEO duration: a long audio stream cannot
    conceal missing video frames. Editorial motion/identity checks remain manual.
    """
    path = ctx.resolve(scene.visual.path)
    rejected = ctx.project.options.get("rejected_clip_sha256", {}).get(scene.scene_id, [])
    if rejected and path.is_file():
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() in rejected:
                return "clip rejected by creator; replace this scene instead of resuming the rejected file"
    try:
        info = probe(path, scene_id=scene.scene_id)
    except StudioError as exc:
        return str(exc)
    if not info.has_video or info.fps <= 0:
        return "file has no timed video stream"
    stream = next(s for s in info.raw.get("streams", [])
                  if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"))
    if info.vcodec in {"png", "mjpeg", "webp", "gif", "bmp", "tiff"}:
        return "still/animated image is not an imported video clip"
    try:
        duration = float(stream.get("duration") or 0)
        if not duration and stream.get("duration_ts") is not None:
            duration = float(stream["duration_ts"]) * float(Fraction(stream["time_base"]))
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        duration = 0
    if not math.isfinite(duration) or duration <= 0:
        return "video-stream duration is unavailable; remux the clip before import"
    # Allow at most two decoded frames of rounding, not a scene-long freeze.
    if duration + 2 / info.fps < (scene.duration_sec or 0):
        return f"video is {duration:.3f}s; scene needs {scene.duration_sec}s (no freeze fallback)"
    minimum = int(ctx.project.options.get("clip_min_short_side", 720))
    if min(info.width, info.height) < minimum:
        return f"native video is {info.width}x{info.height}; short side must be at least {minimum}px"
    target = ctx.fmt
    if info.height <= 0 or abs(info.width / info.height / (target.width / target.height) - 1) > 0.03:
        return f"aspect ratio {info.width}x{info.height} does not match {target.width}x{target.height}"
    return None
