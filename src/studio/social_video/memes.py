"""Meme library: download starter packs and index everything under memes/."""
from __future__ import annotations

import html
import re
from pathlib import Path

import requests

from .util import MEMES, log, media_duration, read_json, write_json

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) threadreel/1.0"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SOUND_EXT = {".mp3", ".wav", ".ogg", ".m4a"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}   # reaction clips with their own sound
PREFIX = {"image": "i:", "sound": "s:", "video": "v:"}
LIBRARY = MEMES / "library.json"
META = MEMES / "meta.json"  # names/extra info for downloaded files, keyed by relative path

DEFAULT_SOUND_QUERIES = [
    "vine boom", "bruh", "sad violin", "anime wow", "emotional damage", "laugh track",
    "airhorn", "fbi open up", "windows xp error", "dun dun dun", "crickets", "applause",
    "huh cat", "oh no no no", "spongebob disappointed", "taco bell bong", "rizz",
    "metal pipe", "ding", "record scratch",
]
MAX_SOUND_BYTES = 3_000_000
MAX_IMAGE_BYTES = 6_000_000
INSTANT_RE = re.compile(
    r"play\('(/media/sounds/[^']+)'.*?class=\"instant-link link-secondary\">([^<]+)<", re.S)


def _download(url: str, dest: Path, max_bytes: int, kinds: tuple[str, ...]) -> bool:
    if dest.exists():
        return False
    resp = requests.get(url, headers=UA, timeout=30)
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "")
    if not ctype.startswith(kinds) or len(resp.content) > max_bytes:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return True


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "x"


def fetch_imgflip(top: int, meta: dict) -> int:
    data = requests.get("https://api.imgflip.com/get_memes", headers=UA, timeout=30).json()
    count = 0
    for m in data["data"]["memes"][:top]:
        ext = Path(m["url"]).suffix or ".jpg"
        rel = f"images/imgflip/{m['id']}{ext}"
        try:
            if _download(m["url"], MEMES / rel, MAX_IMAGE_BYTES, ("image/",)):
                count += 1
        except requests.RequestException as exc:
            log(f"imgflip lỗi {m['name']}: {exc}")
            continue
        meta[rel] = {"name": m["name"], "source": "imgflip", "panels": m.get("box_count", 2)}
    return count


def _myinstants_page(url: str) -> list[tuple[str, str]]:
    body = requests.get(url, headers=UA, timeout=30).text
    return [(path, html.unescape(name).strip()) for path, name in INSTANT_RE.findall(body)]


def fetch_myinstants(vn_pages: int, queries: list[str], meta: dict) -> int:
    found: list[tuple[str, str, str]] = []
    for page in range(1, vn_pages + 1):
        try:
            for path, name in _myinstants_page(f"https://www.myinstants.com/en/index/vn/?page={page}"):
                found.append((path, name, "vn-trending"))
        except requests.RequestException as exc:
            log(f"myinstants VN trang {page} lỗi: {exc}")
    for q in queries:
        try:
            hits = _myinstants_page(
                "https://www.myinstants.com/en/search/?" + requests.compat.urlencode({"name": q}))
        except requests.RequestException as exc:
            log(f"myinstants '{q}' lỗi: {exc}")
            continue
        found.extend((path, name, q) for path, name in hits[:1])

    count = 0
    for path, name, tag in found:
        rel = f"sounds/myinstants/{_slug(Path(path).stem)}.mp3"
        try:
            if _download("https://www.myinstants.com" + path, MEMES / rel, MAX_SOUND_BYTES,
                         ("audio/", "application/octet-stream")):
                count += 1
        except requests.RequestException as exc:
            log(f"Tải âm thanh lỗi '{name}': {exc}")
            continue
        if (MEMES / rel).exists():
            meta[rel] = {"name": name, "source": "myinstants", "tag": tag}
    return count


def fetch(cfg: dict) -> None:
    meta = read_json(META, {})
    mcfg = cfg["memes"]
    log("Tải ảnh meme từ Imgflip…")
    n_img = fetch_imgflip(mcfg["imgflip_top"], meta)
    log("Tải âm thanh meme từ Myinstants (trending VN + từ khóa)…")
    n_snd = fetch_myinstants(mcfg["myinstants_vn_pages"],
                             mcfg["sound_queries"] or DEFAULT_SOUND_QUERIES, meta)
    write_json(META, meta)
    log(f"Đã tải mới {n_img} ảnh, {n_snd} âm thanh")
    scan()


def _name_from_file(path: Path) -> str:
    return re.sub(r"[_-]+", " ", path.stem).strip()


def scan() -> dict:
    """Index every image/sound/video under memes/, keeping known durations."""
    meta = read_json(META, {})
    old = {item["file"]: item for item in read_json(LIBRARY, {"items": []})["items"]}
    items = []
    for path in sorted(MEMES.rglob("*")):
        ext = path.suffix.lower()
        if ext not in IMAGE_EXT | SOUND_EXT | VIDEO_EXT or not path.is_file():
            continue
        rel = path.relative_to(MEMES).as_posix()
        kind = "image" if ext in IMAGE_EXT else "sound" if ext in SOUND_EXT else "video"
        info = meta.get(rel, {})
        item = {
            "id": PREFIX[kind] + rel.split("/", 1)[-1].rsplit(".", 1)[0],
            "kind": kind,
            "file": rel,
            "name": info.get("name") or _name_from_file(path),
            "source": info.get("source", "custom"),
        }
        if info.get('tag'):
            item['tag'] = info['tag']
        if kind == "image":
            item["panels"] = info.get("panels", 1)
            item["animated"] = ext == ".gif"
        else:
            prev = old.get(rel)
            item["duration"] = prev["duration"] if prev and "duration" in prev else round(
                media_duration(path), 2)
            if info.get("tag"):
                item["tag"] = info["tag"]
        items.append(item)
    items.sort(key=lambda item: (item.get('tag') not in ('vn-curated', 'vn-trending'),
                                 item['kind'], item['name']))
    lib = {"items": items}
    write_json(LIBRARY, lib)
    count = {k: sum(1 for i in items if i["kind"] == k) for k in PREFIX}
    log(f"Thư viện meme: {count['image']} ảnh, {count['sound']} âm thanh, "
        f"{count['video']} video → {LIBRARY.name}")
    return lib


def load() -> dict:
    lib = read_json(LIBRARY)
    return lib if lib else scan()
