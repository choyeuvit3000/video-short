"""Rebuild the reviewed local horror pool. Media stays local; provenance is versioned."""

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import requests

from studio.core.ffmpeg import run_ffmpeg
from studio.social_video.quality import sha256
from studio.social_video.util import ASSETS, ffprobe, run, write_json

REPO = Path(__file__).resolve().parents[1]


def fetch(item, path):
    if path.is_file() and sha256(path) == item["sha256"]:
        return
    response = requests.get(item["url"], timeout=90)
    response.raise_for_status()
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(response.content)
    if sha256(partial) != item["sha256"]:
        raise ValueError(f"Source changed: {path.name}; inspect before admitting it")
    partial.replace(path)


def main():
    library = json.loads((REPO / "assets/shared/horror/library.json").read_text(encoding="utf-8"))
    spec = library["background"]
    backgrounds = ASSETS / "backgrounds"
    backgrounds.mkdir(parents=True, exist_ok=True)
    source = backgrounds / spec["source_name"]
    if not source.is_file():
        uvx = shutil.which("uvx")
        if not uvx:
            raise SystemExit("Install uv/yt-dlp, or place the pinned source file in the local backgrounds folder")
        subprocess.run(
            [
                uvx,
                "--from",
                "yt-dlp",
                "yt-dlp",
                "--no-playlist",
                "--no-progress",
                "-f",
                spec["format"],
                "--write-info-json",
                "-o",
                str(source),
                spec["url"],
            ],
            check=True,
        )
    if sha256(source) != spec["source_sha256"]:
        raise ValueError("Background source changed; inspect selected ranges again before updating its hash")
    source_probe = json.loads(
        run([ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(source)]).stdout
    )["streams"][0]
    if (
        min(source_probe["width"], source_probe["height"]) < 1080
        or float(Fraction(source_probe["r_frame_rate"])) < 59.9
    ):
        raise ValueError("Need native 1080p/60fps; never upscale/interpolate to pass this check")
    previous = (
        {x["file"]: x for x in json.loads((ASSETS / "horror_backgrounds.json").read_text()).get("clips", [])}
        if (ASSETS / "horror_backgrounds.json").is_file()
        else {}
    )
    clips = []
    for i, (start, end) in enumerate(spec["ranges"], 1):
        output = backgrounds / f"horror_rain_reviewed_{i:02d}.mp4"
        relative = output.relative_to(ASSETS).as_posix()
        if not output.is_file() or previous.get(relative, {}).get("sha256") != sha256(output):
            partial = output.with_suffix(".partial.mp4")
            run_ffmpeg(
                [
                    "-ss",
                    str(start),
                    "-i",
                    str(source),
                    "-t",
                    str(end - start),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "16",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(partial),
                ],
                stage="horror-assets",
            )
            partial.replace(output)
        clips.append(
            {
                "file": relative,
                "accepted": True,
                "sha256": sha256(output),
                "width": source_probe["width"],
                "height": source_probe["height"],
                "fps": 60,
                "source_range": [start, end],
                "source": spec["url"],
                "creator": spec["creator"],
                "license": spec["license"],
                "mood": spec["mood"],
                "review_method": spec["review_method"],
                "rejected_features": [],
            }
        )
    write_json(ASSETS / "horror_backgrounds.json", {"version": 1, "clips": clips})
    sounds = ASSETS / "horror_sfx"
    sounds.mkdir(exist_ok=True)
    for item in library["sfx"]:
        fetch(item, sounds / item["file"])
    laugh = sounds / "distant_laugh.wav"
    if not laugh.is_file():
        run_ffmpeg(
            [
                "-i",
                str(sounds / "female_laughter_source.mp3"),
                "-t",
                "1.3",
                "-af",
                "highpass=f=250,lowpass=f=3000,aecho=.7:.35:180|360:.22|.10,afade=t=in:d=.08,afade=t=out:st=1.1:d=.3",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(laugh),
            ],
            stage="horror-laugh",
        )
    write_json(
        sounds / "sources.json",
        {
            "sources": library["sfx"],
            "distant_laugh": "Derived from Mixkit Female cheerful laughter, filtered and echoed",
        },
    )
    print(f"Ready: {len(clips)} reviewed backgrounds; {len(library['sfx']) + 1} reusable SFX")


if __name__ == "__main__":
    main()
