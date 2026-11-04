"""Scene photos for the Reddit videos, found online by an English search query.
Only photos free for commercial use without a credit line: Pixabay / Pexels when config.json has
"images": {"pixabay_key": ..., "pexels_key": ...}, then Openverse CC0 (stock sites first).
Each query's pick is cached per story, and a story never shows the same file twice."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .util import load_config, log, read_json, write_json

UA = {"User-Agent": "threadreel/1.0 (reddit story shorts)"}
FREE = re.compile(r"public domain|^pd|cc0|no restrictions|no known copyright", re.I)
# old book / magazine scans and maps that Commons returns for almost any query
JUNK = re.compile(r"\(1[5-9]\d\d\)|\(14\d{9}\)|magazine|journal|book|catalog|annual|report|"
                  r"map |plate |page |\.pdf|\.djvu|\.svg|\.tif", re.I)


def _commons(query: str) -> list[tuple[str, int, int, str]]:
    import requests

    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=40, params={
        "action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": 40,
        "gsrsearch": f"{query} filetype:bitmap", "prop": "imageinfo",
        "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1600, "format": "json"})
    pages = r.json().get("query", {}).get("pages", {})
    out = []
    for pg in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        ii = pg["imageinfo"][0]
        lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
        if (ii.get("mime") == "image/jpeg" and FREE.search(lic) and not JUNK.search(pg["title"])
                and ii["width"] >= 900 and 0.6 <= ii["width"] / ii["height"] <= 2.2):
            out.append((ii.get("thumburl") or ii["url"], ii["width"], ii["height"], pg["title"]))
    return out


def _pixabay(query: str, key: str) -> list[tuple[str, int, int, str]]:
    import requests

    r = requests.get("https://pixabay.com/api/", timeout=40, params={
        "key": key, "q": query, "image_type": "photo", "orientation": "horizontal",
        "safesearch": "true", "per_page": 20})
    return [(x["largeImageURL"], x["imageWidth"], x["imageHeight"], x["tags"])
            for x in r.json().get("hits", [])]


def _pexels(query: str, key: str) -> list[tuple[str, int, int, str]]:
    import requests

    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key}, timeout=40,
                     params={"query": query, "per_page": 15, "orientation": "landscape"})
    return [(x["src"]["large2x"], x["width"], x["height"], x.get("alt") or query)
            for x in r.json().get("photos", [])]


def _sources() -> list[tuple[str, object]]:
    keys = load_config().get("images", {})
    out = []
    if keys.get("pixabay_key"):
        out.append(("pixabay", lambda q: _pixabay(q, keys["pixabay_key"])))
    if keys.get("pexels_key"):
        out.append(("pexels", lambda q: _pexels(q, keys["pexels_key"])))
    # Commons is left out: for everyday scenes it mostly returns old book scans
    return out + [("stock", lambda q: _openverse(q, stock=True)), ("openverse", _openverse)]


def _openverse(query: str, stock: bool = False) -> list[tuple[str, int, int, str]]:
    import requests

    params = {"q": query, "license": "cc0,pdm", "page_size": 20, "mature": "false"}
    if stock:   # CC0 stock photo sites: sharp, modern pictures
        params["source"] = "stocksnap,rawpixel"
    # the .engineering host still answers when api.openverse.org times out
    r = requests.get("https://api.openverse.engineering/v1/images/", headers=UA, timeout=80,
                     params=params)
    return [(x["url"], x.get("width") or 0, x.get("height") or 0, x["title"])
            for x in r.json().get("results", [])
            if (x.get("width") or 0) >= 900]


def find(query: str, folder: Path) -> Path | None:
    """Download the best free photo for `query` into `folder` (cached)."""
    import requests

    folder.mkdir(parents=True, exist_ok=True)
    index = read_json(folder / "index.json", {})
    if query in index and (folder / index[query]).exists():
        return folder / index[query]
    used = set(index.values())
    for name_, source in _sources():
        try:
            hits = source(query)
        except Exception as e:   # one source down: try the next
            log(f"  ảnh: {name_} lỗi ({type(e).__name__})")
            continue
        for url, _, _, title in hits:
            name = hashlib.sha1(url.encode()).hexdigest()[:12] + ".jpg"
            if name in used:
                continue
            try:
                data = requests.get(url, headers=UA, timeout=60).content
            except Exception:
                continue
            if len(data) < 20_000:
                continue
            (folder / name).write_bytes(data)
            index[query] = name
            write_json(folder / "index.json", index)
            log(f"  ảnh '{query}': {title[:60]}")
            return folder / name
    log(f"  không tìm được ảnh cho '{query}'")
    return None
