"""Refresh real meme sources, preserving provenance and excluding rejected stand-ins."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..core.errors import StudioError
from ..core.ffmpeg import run_ffmpeg
from ..core.media_probe import probe
from .util import MEMES, STUDIO_ROOT, read_json, write_json

CATALOG = STUDIO_ROOT / "assets/shared/memes/funny_threads/library.json"
SOURCES = CATALOG.with_name("sources.json")
WORK = STUDIO_ROOT / "projects/social_video/work/funny_threads/asset_refresh_20261107"
FIELDS = (
    "role",
    "is_meme",
    "funny_threads_allowed",
    "source_url",
    "download_url",
    "sha256",
    "tags",
    "use_when_vn",
    "avoid_when_vn",
    "rights_status",
    "source_checked_at",
    "has_audio",
    "derived_from",
    "audio_review",
    "asr_note",
    "raw_asr",
    "asr_model",
    "mild_profanity",
    "caption_policy",
    "width",
    "height",
)


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Page(HTMLParser):
    def __init__(self, body: str):
        super().__init__()
        self.meta = {}
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta":
            self.meta[values.get("property") or values.get("name")] = values.get("content", "")


def resolve_sound(body: str) -> str:
    """Never mistake a related sound at the bottom of the page for the selected sound."""
    url = Page(body).meta.get("og:audio", "")
    if urlparse(url).hostname not in {"www.myinstants.com", "myinstants.com"}:
        raise ValueError("The sound page has no verified own audio URL")
    return url


def download(url: str, destination: Path, *, limit: int, kind: str) -> tuple[str, bool]:
    with requests.get(url, timeout=(8, 25), stream=True) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("Asset exceeds the download limit")
        if not data:
            raise ValueError("Empty media download")
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = destination.with_name(destination.name + ".candidate")
    candidate.write_bytes(data)
    try:
        if kind == "image":
            with Image.open(candidate) as image:
                image.verify()
        else:
            info = probe(candidate)
            if not info.has_audio or info.duration <= 0:
                raise ValueError("The sound does not decode")
        changed = not destination.is_file() or checksum(candidate) != checksum(destination)
        if changed and destination.is_file():
            history = WORK / "source_history" / (checksum(destination)[:12] + "_" + destination.name)
            history.parent.mkdir(parents=True, exist_ok=True)
            history.write_bytes(destination.read_bytes())
        candidate.replace(destination)
    finally:
        candidate.unlink(missing_ok=True)
    return checksum(destination), changed


def allowed(item: dict) -> bool:
    return (
        item.get("is_meme") is True
        and item.get("funny_threads_allowed") is True
        and item.get("role") in {"reaction", "meme_template", "meme_sound", "sound_effect"}
        and bool(item.get("source_url"))
        and bool(item.get("sha256"))
        and item.get("audio_review") != "SHORT_CLIP_ASR_UNRELIABLE_PREVIEW_BEFORE_USE"
        and (item.get("kind") == "sound" or item.get("visual_review") == "AGENT_INSPECTED")
    )


def load_curated(kind: str | None = None) -> list[dict]:
    items = [
        x for x in read_json(CATALOG, {"items": []})["items"] if allowed(x) and (kind is None or x["kind"] == kind)
    ]
    for item in items:
        if checksum(MEMES / item["file"]) != item["sha256"]:
            raise ValueError(f"Changed meme asset: {item['id']}")
    return items


def _base(name, source_url, stamp, role, **more):
    return {
        "name": name,
        "source_url": source_url,
        "source_checked_at": stamp,
        "role": role,
        "is_meme": True,
        "funny_threads_allowed": True,
        "rights_status": "NO_REUSE_LICENSE_VERIFIED",
        "human_listening": "NOT_CLAIMED",
        **more,
    }


def reaction(spec: dict, stamp: str) -> list[dict]:
    slug = spec["slug"]
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("Invalid reaction filename")
    original = MEMES / "sources/tenor" / f"{slug}.gif"
    selected_url = spec["media"]
    try:
        download(selected_url, original, limit=24_000_000, kind="image")
    except (requests.RequestException, ValueError):
        if not spec.get("fallback_media"):
            raise
        selected_url = spec["fallback_media"]
        download(selected_url, original, limit=24_000_000, kind="image")
    with Image.open(original) as source:
        width, height = source.size
        frames = getattr(source, "n_frames", 1)
    if frames < 2:
        raise ValueError("This source is a still, not a reaction clip")
    video = MEMES / "videos/reaction-real" / f"{slug}.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    identity = checksum(original)
    cached = read_json(video.with_suffix(".source.json"), {})
    if not video.is_file() or cached.get("source_sha256") != identity or cached.get("sha256") != checksum(video):
        run_ffmpeg(
            [
                "-ignore_loop",
                "1",
                "-i",
                str(original),
                "-an",
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,setsar=1,fps=30",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-colorspace",
                "bt709",
                "-color_trc",
                "bt709",
                "-color_primaries",
                "bt709",
                str(video),
            ],
            stage="real_meme_import",
        )
        write_json(video.with_suffix(".source.json"), {"source_sha256": identity, "sha256": checksum(video)})
    info = probe(video)
    poster = MEMES / "images/reaction-real" / f"{slug}.png"
    poster.parent.mkdir(parents=True, exist_ok=True)
    at = min(float(spec["poster_at"]), max(0, info.duration - 0.1))
    run_ffmpeg(["-ss", str(at), "-i", str(video), "-frames:v", "1", str(poster)], stage="meme_still")
    common = _base(
        spec["name"],
        spec["page"],
        stamp,
        "reaction",
        download_url=selected_url,
        source_sha256=identity,
        source_width=width,
        source_height=height,
        source_frame_count=frames,
        use_when_vn=spec["use_when"],
        avoid_when_vn=spec["avoid_when"],
        tags=["vn-reaction-real", slug],
        sound_names=spec["sound_names"],
        reference_match=spec["reference_match"],
        visual_review="PENDING_AGENT_CONTACT_SHEET",
        caption_policy="Keep the actual reaction; no automatic editorial title card",
    )
    items = []
    for path, kind, prefix in [(poster, "image", "i"), (video, "video", "v")]:
        items.append(
            {
                **common,
                "id": f"{prefix}:reaction-real/{slug}",
                "kind": kind,
                "file": path.relative_to(MEMES).as_posix(),
                "sha256": checksum(path),
                "derived_from": original.relative_to(MEMES).as_posix(),
                "duration": info.duration if kind == "video" else None,
                "width": info.width,
                "height": info.height,
                "has_audio": False,
                "panels": 1,
            }
        )
    return items


def sound(spec: dict, stamp: str) -> dict:
    response = requests.get(spec["page"], timeout=(8, 20))
    response.raise_for_status()
    url = resolve_sound(response.text)
    slug = re.sub(r"[^a-z0-9]+", "-", Path(urlparse(url).path).stem.lower()).strip("-")
    path = MEMES / "sounds/myinstants" / f"{slug}.mp3"
    digest, new = download(url, path, limit=6_000_000, kind="audio")
    return _base(
        spec["name"],
        spec["page"],
        stamp,
        "meme_sound",
        id=f"s:myinstants/{slug}",
        kind="sound",
        file=path.relative_to(MEMES).as_posix(),
        sha256=digest,
        download_url=url,
        duration=probe(path).duration,
        has_audio=True,
        changed_or_new=new,
        tags=["vn-source-refreshed"],
        use_when_vn=spec.get("use_when", "Phản ứng ngắn đúng nội dung"),
        avoid_when_vn="Không chồng lời đọc, không cắt giữa câu, không dùng ở nội dung nhạy cảm",
        mild_profanity=spec.get("mild_profanity", False),
        audio_review="SOURCE_AND_DECODE_CHECKED",
    )


def reject_standins(meta: dict) -> list[str]:
    rejected = []
    for rel, item in meta.items():
        if item.get("source") == "threadreel-original" or rel.startswith(("images/vietnam/", "videos/vietnam/")):
            item.update(
                is_meme=False,
                funny_threads_allowed=False,
                role="editorial_overlay",
                exclusion_reason="Creator rejected editorial cards as meme substitutes on 2026-11-07",
            )
            rejected.append(rel)
    originals = STUDIO_ROOT / "assets/shared/overlays/funny_originals/library.json"
    data = read_json(originals, {"items": []})
    data["creator_feedback"] = (
        "Rejected as funny Threads meme substitutes; preserve only as legacy editorial/effect assets."
    )
    for item in data["items"]:
        item.update(is_meme=False, funny_threads_allowed=False)
        if item["kind"] in {"image", "video"}:
            item.update(production_eligible=False, role="editorial_overlay", status="CREATOR_REJECTED_NOT_MEME")
            rejected.append(item["id"])
        else:
            item["role"] = "functional_effect"
    write_json(originals, data)
    return rejected


def refresh() -> dict:
    spec = read_json(SOURCES)
    stamp = datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds")
    WORK.mkdir(parents=True, exist_ok=True)
    meta = read_json(MEMES / "meta.json", {})
    rejected = reject_standins(meta)
    items, failures = [], []
    previous_items = {x["id"]: x for x in read_json(CATALOG, {"items": []})["items"]}
    jobs = [("reaction", x) for x in spec["reactions"]]
    index = requests.get("https://www.myinstants.com/en/index/vn/", timeout=20)
    index.raise_for_status()
    (WORK / "myinstants_vn_snapshot.html").write_text(index.text, encoding="utf-8")
    links = {
        html.unescape(name).strip(): urljoin(index.url, url)
        for url, name in re.findall(r'<a[^>]+href="([^"]*instant/[^\"]+)"[^>]*>([^<]+)', index.text)
    }
    for name in spec["vietnam_sound_names"]:
        if name in links:
            jobs.append(("sound", {"name": name, "page": links[name]}))
        else:
            failures.append({"name": name, "reason": "Exact sound name absent from current Viet Nam index"})
    jobs += [("sound", x) for x in spec["additional_sound_pages"]]

    def fetch(job):
        kind, item = job
        try:
            return reaction(item, stamp) if kind == "reaction" else [sound(item, stamp)], None
        except (requests.RequestException, ValueError, OSError, StudioError) as exc:
            return [], {"name": item["name"], "reason": str(exc)[:300]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        for records, error in pool.map(fetch, jobs):
            items.extend(records)
            if error:
                failures.append(error)
    # Refresh selected classic templates using the actual Imgflip API, never invented URLs.
    api = requests.get("https://api.imgflip.com/get_memes", timeout=20)
    api.raise_for_status()
    templates = {x["id"]: x for x in api.json()["data"]["memes"]}
    for ident in spec["imgflip_ids"]:
        template = templates.get(ident)
        if template is None:
            failures.append({"id": ident, "reason": "Not in current Imgflip catalog; retained existing asset"})
            continue
        path = MEMES / "images/imgflip" / (ident + Path(urlparse(template["url"]).path).suffix)
        try:
            digest, new = download(template["url"], path, limit=8_000_000, kind="image")
            items.append(
                _base(
                    template["name"],
                    f"https://imgflip.com/memetemplate/{ident}",
                    stamp,
                    "meme_template",
                    id=f"i:imgflip/{ident}",
                    kind="image",
                    file=path.relative_to(MEMES).as_posix(),
                    sha256=digest,
                    download_url=template["url"],
                    panels=template.get("box_count", 2),
                    changed_or_new=new,
                    tags=["classic-template"],
                    visual_review="PENDING_AGENT_CONTACT_SHEET",
                    use_when_vn="Chọn theo ý cụ thể; ưu tiên reaction thật cho nhịp chốt",
                    avoid_when_vn="Không tự điền chữ vào mọi khung; không thay bằng thẻ bình luận tự chế",
                )
            )
        except (requests.RequestException, ValueError, OSError) as exc:
            failures.append({"id": ident, "reason": str(exc)[:200]})
    for item in items:
        previous = previous_items.get(item["id"], {})
        if previous.get("sha256") == item["sha256"] and item["kind"] == "sound":
            for field in ("raw_asr", "asr_model", "asr_note", "audio_review"):
                if field in previous:
                    item[field] = previous[field]
        if (
            previous.get("sha256") == item["sha256"]
            and previous.get("source_url") == item["source_url"]
            and previous.get("visual_review") == "AGENT_INSPECTED"
        ):
            item["visual_review"] = "AGENT_INSPECTED"
            item["visual_evidence"] = previous.get("visual_evidence")
        source = "myinstants" if item["kind"] == "sound" else "imgflip" if item["role"] == "meme_template" else "tenor"
        meta.setdefault(item["file"], {}).update(item, source=source)
        if item.get("derived_from"):
            meta.setdefault(item["derived_from"], {}).update(
                catalog_excluded=True,
                source_url=item["source_url"],
                exclusion_reason="Original GIF retained; select the indexed still or video to avoid duplicate entries",
            )
        if item["role"] == "meme_template":
            for other in (MEMES / "images/imgflip").glob(Path(item["file"]).stem + ".*"):
                relative = other.relative_to(MEMES).as_posix()
                if relative != item["file"]:
                    meta.setdefault(relative, {}).update(catalog_excluded=True, superseded_by=item["file"])
    write_json(MEMES / "meta.json", meta)
    catalog = {
        "version": 1,
        "updated_at": stamp,
        "path_root": "projects/social_video/memes",
        "status": "SOURCE_REFRESHED_AWAITING_CREATOR_STYLE_REVIEW",
        "items": items,
        "failures": failures,
        "excluded_standins": rejected,
        "rights_note": spec["rights_note"],
        "selection_policy": (
            "Use a real meme only when it fits the punchline; ordinary photos, screenshots, "
            "titles and closing cards are not meme reactions. No automatic insertion schedule "
            "or synthetic stand-in fallback."
        ),
    }
    write_json(CATALOG, catalog)
    from .memes import scan

    scan()
    make_preview(catalog)
    return {
        "catalog": str(CATALOG),
        "counts": {k: sum(x["kind"] == k for x in items) for k in ["image", "video", "sound"]},
        "changed_or_new_sounds": sum(x.get("changed_or_new", False) for x in items if x["kind"] == "sound"),
        "excluded_standins": len(rejected),
        "failures": failures,
        "preview": str(WORK / "asset_review.html"),
    }


def make_preview(catalog: dict) -> None:
    images = [x for x in catalog["items"] if x["kind"] == "image"]
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 19)
    rows = (len(images) + 4) // 5
    sheet = Image.new("RGB", (1200, rows * 255), "#1b1b1b")
    draw = ImageDraw.Draw(sheet)
    for i, item in enumerate(images):
        image = Image.open(MEMES / item["file"]).convert("RGB")
        image = ImageOps.contain(image, (226, 205), Image.Resampling.LANCZOS)
        x, y = i % 5 * 240, i // 5 * 255
        sheet.paste(image, (x + (240 - image.width) // 2, y))
        draw.text((x + 8, y + 211), item["name"][:24], font=font, fill="white")
    sheet.save(WORK / "real_meme_contact_sheet.jpg", quality=96)
    reactions = [x for x in images if x["role"] == "reaction"]
    reaction_sheet = Image.new("RGB", (900, ((len(reactions) + 2) // 3) * 310), "#1b1b1b")
    reaction_draw = ImageDraw.Draw(reaction_sheet)
    for i, item in enumerate(reactions):
        source = ImageOps.contain(Image.open(MEMES / item["file"]).convert("RGB"), (280, 260), Image.Resampling.LANCZOS)
        x, y = i % 3 * 300, i // 3 * 310
        reaction_sheet.paste(source, (x + (300 - source.width) // 2, y))
        reaction_draw.text((x + 8, y + 270), item["name"].split(" — ")[0][:24], font=font, fill="white")
    reaction_sheet.save(WORK / "reaction_preview.jpg", quality=96)
    cards = []

    def local(file):
        return html.escape(os.path.relpath(MEMES / file, WORK).replace("\\", "/"), quote=True)

    for item in catalog["items"]:
        name = html.escape(item["name"])
        if item["kind"] == "video":
            media = f'<video controls muted loop preload="none" src="{local(item["file"])}"></video>'
        elif item["kind"] == "sound":
            media = f'<audio controls preload="none" src="{local(item["file"])}"></audio>'
        else:
            media = f'<img loading="lazy" src="{local(item["file"])}" alt="{name}">'
        cards.append(
            f"<article><small>{html.escape(item['kind'])}</small><h2>{name}</h2>{media}"
            f"<p>{html.escape(item.get('use_when_vn', ''))}</p><code>{html.escape(item['id'])}</code>"
            f'<p><a href="{html.escape(item["source_url"], quote=True)}">Nguồn</a></p>'
            + (
                "<p>Cần nghe thử: ASR không đáng tin với clip nói rất ngắn này.</p>"
                if item.get("audio_review") == "SHORT_CLIP_ASR_UNRELIABLE_PREVIEW_BEFORE_USE"
                else ""
            )
            + "</article>"
        )
    document = (
        '<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        "<title>Kho meme thật — Threads vui</title><style>"
        "body{background:#181818;color:#eee;font:16px Arial;margin:28px}"
        "main{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px}"
        "article{background:#272727;padding:18px;overflow-wrap:anywhere}h2{font-size:20px}"
        "img,video{width:100%;height:230px;object-fit:contain}audio{width:100%}a{color:#8dceff}code{font-size:12px}"
        "</style><h1>Ảnh, clip và sound meme thật</h1><p>Đây là kho asset để xem/chọn, không phải bố cục video. "
        "Không dùng lại các thẻ chữ hay mèo tự vẽ làm meme. Clip GIF chuyển sang video không có tiếng gốc; "
        "sound được lưu riêng. Mỗi asset có nguồn; tải miễn phí không đồng nghĩa giấy phép sử dụng tự do.</p><main>"
        + "".join(cards)
        + "</main></html>"
    )
    (WORK / "asset_review.html").write_text(document, encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(refresh(), ensure_ascii=False, indent=2))
