"""Shared story layout can carry different sources without changing their attribution."""


def labels(story):
    if story.get("platform") == "original_fiction":
        return "Truyện kỳ dị", "Sáng tác lấy cảm hứng dân gian"
    author = story.get("author", "").lstrip("@")
    if story.get("platform") == "threads":
        return "Threads", "@" + author
    return "r/" + story.get("sub", "nosleep"), "u/" + author


def credit(story):
    if story.get("platform") == "original_fiction":
        works = "; ".join(x["work"] for x in story.get("inspirations", []))
        return f"Truyện hư cấu: {story.get('title', '')}. Lấy cảm hứng: {works}"
    platform, author = labels(story)
    return f"Nguồn: {platform} · {author} · {story.get('url', '')}"


def mode(story):
    if story.get("platform") == "original_fiction":
        return "original_story"
    return "threads_story" if story.get("platform") == "threads" else "reddit"


def write_asset_credits(folder, output, part):
    """Local description-ready attribution for the exact background and sound plan."""
    from pathlib import Path

    from .util import ASSETS, read_json, write_json

    slot = "0" if str(part) == "full" else str(part)
    background = read_json(folder / "background_plan.json", {}).get("slots", {}).get(slot, {})
    sound = read_json(folder / "sound_plan.json", {}).get("parts", {}).get(str(part), {})
    rows = []
    if background.get("attribution"):
        rows.append({"type": "background", **background["attribution"]})
    library = read_json(ASSETS / "horror_sfx/sources.json", {}).get("sources", [])
    by_name = {x["file"]: x for x in library}
    for cue in sound.get("events", []):
        name = Path(cue["path"]).name
        spec = by_name.get("female_laughter_source.mp3" if name == "distant_laugh.wav" else name, {})
        if spec:
            rows.append({"type": "sfx", "used_file": name, **spec})
    if sound.get("music"):
        rows.append(
            {"type": "music", "creator": "Studio horrormusic module", "license": "Locally synthesized by this project"}
        )
    source = read_json(folder / "source.json", {})
    data = {"story_source": credit(source), "assets": rows, "upload_status": "NOT_UPLOADED"}
    write_json(output.with_suffix(".assets.json"), data)
    lines = [data["story_source"]]
    lines += [
        f"{x.get('creator', x.get('used_file', x['type']))}: {x.get('source', '')} — {x.get('license', '')}"
        for x in rows
    ]
    output.with_suffix(".credits.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
