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
        if (
            not output.is_file()
            or previous.get(relative, {}).get("sha256") != sha256(output)
            or previous.get(relative, {}).get("source_range") != [start, end]
        ):
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
    if len(clips) > 1 and spec.get("concat_reviewed_ranges"):
        combined = backgrounds / "horror_rain_reviewed_continuous.mp4"
        combined_rel = combined.relative_to(ASSETS).as_posix()
        components = [x["sha256"] for x in clips]
        if (
            not combined.is_file()
            or previous.get(combined_rel, {}).get("sha256") != sha256(combined)
            or previous.get(combined_rel, {}).get("component_sha256") != components
        ):
            listing = backgrounds / "horror_reviewed_concat.txt"
            listing.write_text(
                "ffconcat version 1.0\n" + "\n".join(f"file '{Path(x['file']).name}'" for x in clips) + "\n",
                encoding="utf-8",
            )
            partial = combined.with_suffix(".partial.mp4")
            run_ffmpeg(
                [
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(listing),
                    "-an",
                    "-c:v",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(partial),
                ],
                stage="horror-assets-join",
            )
            partial.replace(combined)
        clips.append(
            {
                **clips[0],
                "file": combined_rel,
                "sha256": sha256(combined),
                "source_range": [spec["ranges"][0][0], spec["ranges"][-1][1]],
                "source_ranges": spec["ranges"],
                "component_sha256": components,
                "review_method": "Join of reviewed visible cool native 1080p60 ranges, with no interpolation",
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
