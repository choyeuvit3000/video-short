"""Subpixel camera sampling for still-art video; source artwork stays immutable."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image

from .util import ffmpeg

MOTION_VERSION = "affine-subpixel-smootherstep-v1"


def zoom_at(frame: int, frames: int, *, zoom_in: bool = True) -> float:
    if frames < 1 or not 0 <= frame < frames:
        raise ValueError("Camera frame is outside its scene")
    t = frame / max(1, frames - 1)
    ease = t * t * t * (t * (t * 6 - 15) + 10)
    return 1 + .045 * (ease if zoom_in else 1 - ease)


def camera_affine(image_size: tuple[int, int], frame: int, frames: int, *,
                  zoom_in: bool = True, crop: dict | None = None,
                  output_size: tuple[int, int] = (1920, 1080)) -> tuple[float, ...]:
    """Inverse sample coordinates; never round or accumulate the moving crop."""
    iw, ih = image_size
    ow, oh = output_size
    if min(iw, ih, ow, oh) <= 0:
        raise ValueError("Camera dimensions must be positive")
    left, top, width, height = 0., 0., float(iw), float(ih)
    if crop:
        width, height = float(crop["w"]), float(crop["h"])
        if not 0 < width <= iw or not 0 < height <= ih:
            raise ValueError("Camera crop is larger than the source artwork")
        # Match FFmpeg's existing bounded framing, retaining fractional camera motion.
        left = min(max(float(crop["x"]), 0), iw - width)
        top = min(max(float(crop["y"]), 0), ih - height)
    if not all(math.isfinite(v) for v in (left, top, width, height)):
        raise ValueError("Camera crop must be finite")
    scale = max(ow / width, oh / height) * zoom_at(frame, frames, zoom_in=zoom_in)
    inv = 1 / scale
    return (inv, 0., left + width / 2 - ow * inv / 2,
            0., inv, top + height / 2 - oh * inv / 2)


def sample_frame(image: Image.Image, frame: int, frames: int, *, zoom_in: bool = True,
                 crop: dict | None = None, output_size: tuple[int, int] = (1920, 1080)) -> Image.Image:
    matrix = camera_affine(image.size, frame, frames, zoom_in=zoom_in, crop=crop, output_size=output_size)
    return image.transform(output_size, Image.Transform.AFFINE, matrix, resample=Image.Resampling.BICUBIC)


def encode_scene(image_path: Path, output: Path, *, frames: int, first_frame: int,
                 zoom_in: bool, crop: dict | None, work: Path, captions: bool = True) -> None:
    """Generate each frame directly from the same still; composite captions afterwards."""
    filters = (f"setpts=PTS+{first_frame / 30:.8f}/TB,ass=filename='captions.ass',"
               "setpts=PTS-STARTPTS,setsar=1") if captions else "setsar=1"
    cmd = [ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
           "-video_size", "1920x1080", "-framerate", "30", "-i", "pipe:0", "-vf", filters,
           "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-threads", "4", "-pix_fmt", "yuv420p", str(output.resolve())]
    log = output.with_suffix(".encode.log")
    with Image.open(image_path) as original, log.open("wb") as errors:
        image = original.convert("RGB")
        proc = subprocess.Popen(cmd, cwd=work, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            for frame in range(frames):
                rendered = sample_frame(image, frame, frames, zoom_in=zoom_in, crop=crop)
                proc.stdin.write(rendered.tobytes())
                rendered.close()
            proc.stdin.close()
            code = proc.wait(timeout=60)
        except BaseException:
            proc.kill()
            proc.wait(timeout=10)
            raise
        finally:
            image.close()
    if code:
        raise RuntimeError("Stable camera encode failed: " + log.read_text(encoding="utf-8", errors="replace")[-2500:])
