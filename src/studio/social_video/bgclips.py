"""Background footage for the Reddit videos: each video part plays one gameplay video from
assets/backgrounds, picked at random (least used first), straight through from a random point.
Landscape gameplay is centre-cropped to 9:16 with its top HUD dropped."""

from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path

from .util import ASSETS, ROOT, ffprobe, media_duration, read_json, run, write_json

SOURCES = ASSETS / "backgrounds"
USAGE = ROOT / "cache" / "bg_usage.json"
EDGE_SEC = 8  # skip the first and last seconds of a recording (menus, fades)


@lru_cache(maxsize=4096)
def _cached_duration(path, mtime_ns, size):
    return media_duration(Path(path))


def _duration(path):
    stat = path.stat()
    return _cached_duration(str(path), stat.st_mtime_ns, stat.st_size)


def _sources() -> list[Path]:
    clips = sorted(p for p in (ASSETS / "bgclips" / "prepared").glob("*.mp4") if not p.name.endswith(".partial.mp4"))
    if clips:
        return clips
    return sorted(p for p in SOURCES.glob("*") if p.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"})


def _crop(src: Path, aspect: float) -> str:
    """Centre crop to width/height `aspect` (9:16 full screen, 9:8 under a scene photo)."""
    probe = run(
        [
            ffprobe(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(src),
        ]
    ).stdout
    w, h = map(int, probe.strip().split(",")[:2])
    if aspect < 1 and w > h:  # landscape gameplay, full screen: drop the top 6% (boss bar) too
        return f"crop=trunc(ih*0.94*{aspect:.5f}/2)*2:trunc(ih*0.94/2)*2:(iw-ow)/2:ih-oh,"
    if w / h > aspect:
        return f"crop=trunc(ih*{aspect:.5f}/2)*2:ih:(iw-ow)/2:0,"
    return f"crop=iw:trunc(iw/{aspect:.5f}/2)*2:0:(ih-oh)/2,"


def pick(
    seconds: float, rng: random.Random, aspect: float = 9 / 16, family: str = "any"
) -> tuple[Path, float, str] | None:
    """(source, start second, crop filter to `aspect`) for one part `seconds` long, or None."""
    if family == "horror":
        pool = horror_pool()
        if not pool:
            raise ValueError("No reviewed 1080p/60fps horror background; run scripts/prepare_horror_assets.py")
    else:
        pool = sorted(SOURCES.glob("minecraft*.mp4")) if family == "minecraft" else _sources()
    if family == "minecraft" and not pool:
        raise ValueError("No imported Minecraft background is available")
    if not pool:
        return None
    usage = read_json(USAGE, {})
    long_enough = [p for p in pool if _duration(p) >= seconds]
    if long_enough:
        pool = long_enough
    low = min(usage.get(p.name, 0) for p in pool)
    src = rng.choice([p for p in pool if usage.get(p.name, 0) == low])
    usage[src.name] = usage.get(src.name, 0) + 1
    write_json(USAGE, usage)
    total = _duration(src)
    margin = EDGE_SEC if total >= seconds + 2 * EDGE_SEC else 0
    start = rng.uniform(margin, max(margin, total - seconds - margin))
    return src, start, _crop(src, aspect)


def horror_pool():
    """Only reviewed native-quality clips; old lava/minecart footage is never a fallback."""
    import json
    from fractions import Fraction

    from .quality import sha256

    entries = read_json(ASSETS / "horror_backgrounds.json", {}).get("clips", [])
    pool = []
    for item in entries:
        path = (ASSETS / item["file"]).resolve()
        if not path.is_relative_to(ASSETS.resolve()):
            raise ValueError("Background catalog path leaves the asset library")
        if not item.get("accepted") or item.get("rejected_features"):
            continue
        if not path.is_file() or sha256(path) != item.get("sha256"):
            raise ValueError("Reviewed horror background missing or changed; rebuild asset library")
        data = json.loads(
            run(
                [
                    ffprobe(),
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,r_frame_rate",
                    "-of",
                    "json",
                    str(path),
                ]
            ).stdout
        )["streams"][0]
        if min(data["width"], data["height"]) >= 1080 and float(Fraction(data["r_frame_rate"])) >= 59.9:
            pool.append(path)
    return pool


def _visible(folder, part, candidate, seconds):
    from PIL import Image, ImageStat

    from ..core.ffmpeg import run_ffmpeg

    source, start, crop = candidate
    length = _duration(source)
    good = []
    for i, offset in enumerate((1, seconds / 2, max(1, seconds - 1))):
        frame = folder / "work/bg_checks" / f"part{part}_{i}.jpg"
        frame.parent.mkdir(parents=True, exist_ok=True)
        at = (start + offset) % max(1, length - 0.1)
        run_ffmpeg(
            ["-ss", str(at), "-i", str(source), "-vf", crop + "scale=160:284", "-frames:v", "1", str(frame)],
            stage="background-check",
        )
        gray = Image.open(frame).convert("L")
        hist = gray.histogram()
        good.append(ImageStat.Stat(gray).mean[0] > 8 and sum(hist[24:]) / (gray.width * gray.height) > 0.12)
    return good[0] and sum(good) >= 2


def planned(folder: Path, part: int, seconds: float, rng: random.Random, aspect: float = 9 / 16, family: str = "any"):
    """Choose once so a random background remains the one shown in the review preview."""
    from ..core.errors import ManualGateRequired
    from .quality import sha256

    path = folder / "background_plan.json"
    plan = read_json(path, {"slots": {}})
    item = plan["slots"].get(str(part))
    if item:
        if item.get("aspect") != aspect or item.get("family") != family:
            raise ManualGateRequired("background", "Bố cục hoặc nhóm nền đã đổi; cần chuẩn bị lại bản xem trước.")
        source = Path(item["source"])
        if not source.is_file() or sha256(source) != item["sha256"]:
            raise ManualGateRequired("background", "Video nền đã thay đổi; cần chuẩn bị lại bản xem trước.")
        return source, item["start"], item["crop"]
    for _ in range(12):
        chosen = pick(seconds, rng, aspect, family)
        if not chosen:
            return None
        if not _visible(folder, part, chosen, seconds):
            continue
        source, start, crop = chosen
        plan["slots"][str(part)] = {
            "source": str(source.resolve()),
            "start": start,
            "crop": crop,
            "aspect": aspect,
            "family": family,
            "sha256": sha256(source),
            "attribution": next(
                (
                    {k: x.get(k) for k in ("source", "creator", "license", "source_range")}
                    for x in read_json(ASSETS / "horror_backgrounds.json", {}).get("clips", [])
                    if (ASSETS / x["file"]).resolve() == source.resolve()
                ),
                {},
            ),
        }
        write_json(path, plan)
        return chosen
    raise ManualGateRequired("background", "Chưa chọn được nền đủ rõ; cần kiểm tra lại kho nền trước khi dựng.")
