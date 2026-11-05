"""Recompose a landscape full story from approved narration, without Shorts title/outro repetition."""

import copy
import random
from pathlib import Path

from PIL import Image

from ..core.outputs import organized_output
from . import bgclips
from .util import FINAL_OUTPUT, ffmpeg, media_duration, run


def export_full(story_id, story, vi, groups, voiced, cfg, folder):
    from .quality import publish
    from .reddit import _join
    from .story_source import mode

    work = folder / "full"
    work.mkdir(exist_ok=True)
    from ..core.subtitles import load_words
    from .story_cards import timed_cards
    from .util import read_json

    manifest = read_json(folder / "voice_manifest.json", {})
    lines = []
    last = None
    for index, (_wav, seconds) in enumerate(voiced):
        words, origin = load_words(Path(manifest["timing_files"][index]))
        if origin not in ("faster_whisper", "manual"):
            raise ValueError("Full story needs real speech anchors")
        for j, (frame, share) in enumerate(timed_cards(story, words, seconds, work / "phrase_cards", f"s{index:04d}")):
            canvas = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
            canvas.paste(Image.open(frame).crop((0, 0, 1080, 1080)), (0, 0))
            last = work / f"c{index:04d}_{j:03d}.png"
            canvas.save(last)
            lines += [f"file '{last.name}'", f"duration {seconds * share:.6f}"]
    lines.append(f"file '{last.name}'")
    (work / "cards.txt").write_text("ffconcat version 1.0\n" + "\n".join(lines) + "\n", encoding="utf-8")
    narration = work / "narration.wav"
    _join([p for p, t in voiced], narration, 0.0)
    seconds = media_duration(narration)
    bg = bgclips.planned(
        folder, 0, seconds, random.Random(story_id), 820 / 1080, family=cfg["reddit"].get("background_family", "horror")
    )
    if not bg:
        raise RuntimeError("No background available for full landscape video")
    src, start, crop = bg
    from .story_sound import mix

    sound = work / "sound.wav"
    mix(folder, "full", narration, sound, seconds)
    draft = work / "full_unmastered.mp4"
    run(
        [
            ffmpeg(),
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            "cards.txt",
            "-stream_loop",
            "-1",
            "-ss",
            str(start),
            "-i",
            str(src.resolve()),
            "-i",
            str(sound.resolve()),
            "-filter_complex",
            f"[1:v]{crop}scale=820:1080,fps=30,setsar=1,{bgclips.horror_grade(cfg)},"
            "pad=1920:1080:1100:0:color=0x101822[bg];[bg][0:v]overlay=0:0:format=auto,format=yuv420p[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(draft.resolve()),
        ],
        cwd=work,
    )
    full_mode = mode(story) + "_full"
    outdir = organized_output(FINAL_OUTPUT, full_mode, folder / "full_output_location.json")
    out = outdir / f"{full_mode}__{story_id}.mp4"
    wide = copy.deepcopy(cfg)
    wide["video"].update(width=1920, height=1080)
    publish(draft, out, wide)
    from .story_source import write_asset_credits

    write_asset_credits(folder, out, "full")
    return out
