"""Visual and reaction decisions for an approved Funny Threads script."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from ..core.ffmpeg import run_ffmpeg
from ..core.user_review import read
from .reaction_assets import MEMES, load_curated

WIDTH, HEIGHT = 1080, 1920


def load_edit(folder, plan):
    edit = read(folder / "funny_edit.json")
    if edit is None:
        return None
    if type(edit.get("revision")) is not int or edit["revision"] < 2:
        raise ValueError("A Funny Threads edit needs a revision number of at least two")
    hook = edit.get("hook", [])
    if not 1 <= len(hook) <= 2 or not all(isinstance(x, str) and x.strip() for x in hook):
        raise ValueError("The edit hook needs one or two short lines")
    if sum(len(x.split()) for x in hook) > 8:
        raise ValueError("The edit hook must fit eight words")
    crops = plan["source"]["crops"]
    known = {x["id"]: x for x in load_curated()}
    selected = {}

    def asset(ident, kind):
        item = known.get(ident)
        if item is None or item["kind"] != kind or (kind != "sound" and item["role"] != "reaction"):
            raise ValueError(f"Select a checked {kind} from the Funny Threads library: {ident}")
        selected[ident] = {**item, "path": str(MEMES / item["file"])}
        return item

    if edit["closing_crop"] not in crops or edit["cover"]["source_crop"] not in crops:
        raise ValueError("The cover and ending must use a captured source card")
    asset(edit["cover"]["reaction_id"], "image")
    reactions = {b["id"]: b for b in plan["beats"] if b["kind"] == "reaction"}
    if set(edit["reactions"]) != set(reactions):
        raise ValueError("Choose a real reaction for each planned reaction beat")
    for ident, cue in edit["reactions"].items():
        if cue["source_crop"] not in crops:
            raise ValueError("A reaction must retain the source card it responds to")
        video = asset(cue["video_id"], "video")
        start = float(cue.get("start_seconds", 0))
        if not math.isfinite(start) or start < 0 or start + float(reactions[ident]["duration"]) > video["duration"]:
            raise ValueError(f"Reaction clip cannot cover the slot: {cue['video_id']}")
        if cue.get("sound_id"):
            asset(cue["sound_id"], "sound")
    return {**edit, "assets": selected}


def reaction_geometry(asset, plan, crop):
    width, height = asset["width"], asset["height"]
    height = min(width, height)
    scale = min(396 / width, 218 / height)
    w, h = max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
    card = _card(plan, crop, (880, 1090))
    return 932 - w, 970 - card.height // 2 - 12 - h, w, h


def _title(im, lines, y, max_width):
    draw = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        size = 92
        while True:
            font = ImageFont.truetype("C:/Windows/Fonts/arialbi.ttf", size)
            if draw.textlength(line, font=font) <= max_width or size <= 34:
                break
            size -= 2
        draw.text(
            (500, y + i * 100), line, font=font, anchor="mt", stroke_width=5,
            stroke_fill="#201323", fill=("#ffd8f3", "#fff2a7")[i],
        )


def _card(plan, ident, box):
    with Image.open(plan["source"]["crops"][ident]["path"]) as im:
        return ImageOps.contain(im.convert("RGBA"), box, Image.Resampling.LANCZOS)


def make_layouts(plan, edit, out):
    results = []
    for beat in plan["beats"]:
        im = Image.new("RGBA", (WIDTH, HEIGHT))
        cue = edit["reactions"].get(beat["id"])
        crop = cue["source_crop"] if cue else beat.get("source_crop", edit["closing_crop"])
        media = beat.get("media_crop")
        if media:
            card = _card(plan, crop, (880, 310))
            photo = _card(plan, media, (880, 850))
            top = max(380, 965 - (card.height + photo.height + 10) // 2)
            im.alpha_composite(card, (500 - card.width // 2, top))
            im.alpha_composite(photo, (500 - photo.width // 2, top + card.height + 10))
        else:
            card = _card(plan, crop, (880, 1090))
            top = 970 - card.height // 2
            im.alpha_composite(card, (500 - card.width // 2, top))
        if beat is plan["beats"][0]:
            _title(im, edit["hook"], 435, 860)
        _credit(im, plan)
        path = out / f"layout_{beat['id']}.png"
        im.save(path)
        results.append(path)
    return results


def _credit(im, plan):
    draw = ImageDraw.Draw(im)
    draw.text(
        (64, 1636), f"Threads  ·  @{plan['source']['author']}",
        font=ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 29),
        fill="#ffffff", stroke_width=2, stroke_fill="#201723",
    )


def make_cover(folder, plan, edit, timeline):
    cover = folder / "cover_preview.png"
    start = plan["background"]["start_seconds"] + timeline["cover_frames"][0] / timeline["fps"]
    frame = folder / "work/funny_voice/cover_background.png"
    run_ffmpeg(
        ["-ss", str(start), "-i", plan["background"]["path"], "-vf", "scale=1080:1920", "-frames:v", "1", str(frame)],
        stage="funny_cover_background",
    )
    with Image.open(frame) as bg:
        im = ImageEnhance.Brightness(bg.convert("RGBA")).enhance(0.72)
    card = _card(plan, edit["cover"]["source_crop"], (780, 1015))
    im.alpha_composite(card, (498 - card.width // 2, 595))
    with Image.open(edit["assets"][edit["cover"]["reaction_id"]]["path"]) as reaction:
        photo = ImageOps.contain(reaction.convert("RGBA"), (275, 280), Image.Resampling.LANCZOS)
    im.alpha_composite(photo, (932 - photo.width, 505))
    _title(im, edit["hook"], 258, 890)
    _credit(im, plan)
    im.convert("RGB").save(cover)
