"""Background footage for the Reddit videos: each video part plays one gameplay video from
assets/backgrounds, picked at random (least used first), straight through from a random point.
Landscape gameplay is centre-cropped to 9:16 with its top HUD dropped."""
from __future__ import annotations

import random
from pathlib import Path

from .util import ASSETS, ROOT, ffprobe, media_duration, read_json, run, write_json

SOURCES = ASSETS / "backgrounds"
USAGE = ROOT / "cache" / "bg_usage.json"
EDGE_SEC = 8        # skip the first and last seconds of a recording (menus, fades)


def _sources() -> list[Path]:
    clips = sorted(p for p in (ASSETS / 'bgclips' / 'prepared').glob('*.mp4')
                   if not p.name.endswith('.partial.mp4'))
    if clips:
        return clips
    return sorted(p for p in SOURCES.glob("*")
                  if p.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"})


def _crop(src: Path, aspect: float) -> str:
    """Centre crop to width/height `aspect` (9:16 full screen, 9:8 under a scene photo)."""
    probe = run([ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=p=0", str(src)]).stdout
    w, h = map(int, probe.strip().split(",")[:2])
    if aspect < 1 and w > h:   # landscape gameplay, full screen: drop the top 6% (boss bar) too
        return "crop=trunc(ih*0.94*9/16/2)*2:trunc(ih*0.94/2)*2:(iw-ow)/2:ih-oh,"
    if w / h > aspect:
        return f"crop=trunc(ih*{aspect:.5f}/2)*2:ih:(iw-ow)/2:0,"
    return f"crop=iw:trunc(iw/{aspect:.5f}/2)*2:0:(ih-oh)/2,"


def pick(seconds: float, rng: random.Random, aspect: float = 9 / 16) -> tuple[Path, float, str] | None:
    """(source, start second, crop filter to `aspect`) for one part `seconds` long, or None."""
    pool = _sources()
    if not pool:
        return None
    usage = read_json(USAGE, {})
    long_enough = [p for p in pool if media_duration(p) >= seconds]
    if long_enough:
        pool = long_enough
    low = min(usage.get(p.name, 0) for p in pool)
    src = rng.choice([p for p in pool if usage.get(p.name, 0) == low])
    usage[src.name] = usage.get(src.name, 0) + 1
    write_json(USAGE, usage)
    total = media_duration(src)
    margin = EDGE_SEC if total >= seconds + 2 * EDGE_SEC else 0
    start = rng.uniform(margin, max(margin, total - seconds - margin))
    return src, start, _crop(src, aspect)
