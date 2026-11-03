"""ffprobe wrapper returning a small typed summary."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .errors import StudioError
from .ffmpeg import ffprobe_bin


@dataclass
class MediaInfo:
    path: Path
    duration: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vcodec: str | None = None
    pix_fmt: str | None = None
    sar: str | None = None
    acodec: str | None = None
    sample_rate: int = 0
    channels: int = 0
    raw: dict = field(default_factory=dict, repr=False)


def _fps(rate: str | None) -> float:
    if not rate or rate in ("0/0", "0"):
        return 0.0
    try:
        return float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path, *, scene_id: str | None = None) -> MediaInfo:
    if not path.is_file() or path.stat().st_size == 0:
        raise StudioError(f"Media file missing or empty: {path}", code="missing_media", scene_id=scene_id)
    proc = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if proc.returncode != 0:
        raise StudioError(f"ffprobe cannot read {path}: {proc.stderr.strip()[-500:]}", code="unreadable_media",
                          scene_id=scene_id)
    data = json.loads(proc.stdout or "{}")
    info = MediaInfo(path=path, raw=data)
    fmt = data.get("format", {})
    try:
        info.duration = float(fmt.get("duration", 0) or 0)
    except ValueError:
        info.duration = 0.0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.has_video:
            if s.get("disposition", {}).get("attached_pic"):
                continue
            info.has_video = True
            info.width = int(s.get("width", 0))
            info.height = int(s.get("height", 0))
            info.fps = _fps(s.get("avg_frame_rate")) or _fps(s.get("r_frame_rate"))
            info.vcodec = s.get("codec_name")
            info.pix_fmt = s.get("pix_fmt")
            info.sar = s.get("sample_aspect_ratio")
        elif s.get("codec_type") == "audio" and not info.has_audio:
            info.has_audio = True
            info.acodec = s.get("codec_name")
            info.sample_rate = int(s.get("sample_rate", 0) or 0)
            info.channels = int(s.get("channels", 0) or 0)
    return info
