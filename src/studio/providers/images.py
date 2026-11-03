"""Real photos for knowledge scenes, from the Wikimedia Commons API (the official MediaWiki API, no key).

Only freely licensed files are used (public domain, CC0, CC BY, CC BY-SA). Each pick keeps its author, licence
and file page, so the credit is shown on screen and listed in output/metadata.md. Search answers and downloads
are cached in cache/images/ (by query / by file URL), so re-runs do not hit the API again.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from ..core.cache import Cache, cache_key
from ..core.errors import ProviderUnavailable
from ..core.logging_utils import get_logger

log = get_logger()

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia asks API clients for a descriptive User-Agent with a way to reach the operator
UA = "video-short-studio/0.1 (https://github.com/choyeuvit3000/video-short)"
_FREE = re.compile(r"^(public domain|pd(-\S+)?|cc0( 1\.0)?|cc[ -]by(-sa)?([ -][\d.]+)?( \S+)?)$", re.I)
# Commons renders SVG diagrams to PNG thumbnails, so drawings are usable too
_MIMES = {"image/jpeg": ".jpg", "image/png": ".png", "image/svg+xml": ".png"}


@dataclass
class Photo:
    title: str
    url: str  # the (scaled) file to download
    page: str  # the file's description page on Commons
    author: str
    license: str
    license_url: str
    width: int
    height: int
    mime: str

    def credit(self) -> str:
        return f"Ảnh: {self.author} · {self.license} · Wikimedia Commons"


def _plain(value: object, limit: int = 80) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _author(value: object) -> str:
    """Artist HTML often repeats the name (link text + hidden label): "Unknown author Unknown author" -> once."""
    text = _plain(value)
    words = text.split()
    half = len(words) // 2
    if half and len(words) % 2 == 0 and words[:half] == words[half:]:
        text = " ".join(words[:half])
    if text.lower() in {"unknown", "unknown author", "anonymous", "anonymous author"}:
        return "không rõ tác giả"
    return text or "không rõ tác giả"


def _words(text: str) -> set[str]:
    """Lower-case words without accents ("Ngô Quyền" -> {"ngo", "quyen"}), so Vietnamese titles match."""
    t = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return {w for w in re.findall(r"\w+", t) if len(w) > 2}


def is_free(license_name: str) -> bool:
    return bool(_FREE.match(license_name.strip()))


def _client(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30)


def search_commons(query: str, *, limit: int = 15, min_width: int = 800, width: int = 1600,
                   client: httpx.Client | None = None) -> list[Photo]:
    """Freely licensed photos / drawings matching `query`, best match first."""
    params = {
        "action": "query", "format": "json", "formatversion": "2", "generator": "search",
        "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": str(limit),
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": str(width),
    }
    http = _client(client)
    try:
        r = http.get(API, params=params)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderUnavailable(f"Wikimedia Commons search failed: {type(e).__name__}",
                                  code="images_offline") from None
    finally:
        if client is None:
            http.close()
    pages = sorted((data.get("query") or {}).get("pages") or [], key=lambda pg: pg.get("index", 0))
    words = _words(query)
    scored: list[tuple[int, Photo]] = []
    for pg in pages:
        info = (pg.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _plain((meta.get("LicenseShortName") or {}).get("value"))
        w, h = int(info.get("width") or 0), int(info.get("height") or 0)
        svg = info.get("mime") == "image/svg+xml"
        if info.get("mime") not in _MIMES or (w < min_width and not svg) or not h or not 0.4 <= w / h <= 2.5:
            continue
        if not is_free(lic) or str((meta.get("NonFree") or {}).get("value", "")).lower() == "true":
            continue
        # full-text search is loose ("seasons" also finds a Pluto map): keep files whose title or
        # description shares words with the query, title words counting double
        title_words = _words(str(pg.get("title", "")))
        desc_words = _words(_plain((meta.get("ImageDescription") or {}).get("value"), 2000))
        score = 2 * len(words & title_words) + len(words & desc_words)
        if words and score == 0:
            continue
        scored.append((score, Photo(
            title=str(pg.get("title", "")), url=str(info.get("thumburl") or info.get("url")),
            page=str(info.get("descriptionurl") or ""), author=_author((meta.get("Artist") or {}).get("value")),
            license=lic, license_url=str((meta.get("LicenseUrl") or {}).get("value", "")),
            width=w, height=h, mime=str(info["mime"]))))
    return [ph for _, ph in sorted(scored, key=lambda x: -x[0])]  # stable: search rank breaks ties


def download(photo: Photo, dest_stem: Path, *, client: httpx.Client | None = None) -> Path:
    """Save the photo as <dest_stem>.jpg/.png (temp file, then rename) and check that it opens."""
    from PIL import Image

    dest = dest_stem.with_suffix(_MIMES[photo.mime])
    tmp = dest.with_name(dest.name + ".part")
    http = _client(client)
    try:
        r = http.get(photo.url)
        r.raise_for_status()
        tmp.write_bytes(r.content)
        with Image.open(tmp) as im:
            im.verify()
    except (httpx.HTTPError, OSError, ValueError) as e:
        tmp.unlink(missing_ok=True)
        raise ProviderUnavailable(f"download of {photo.title} failed: {type(e).__name__}",
                                  code="images_offline") from None
    finally:
        if client is None:
            http.close()
    tmp.replace(dest)
    return dest


def _relaxed(query: str, min_words: int = 2) -> list[str]:
    """The query, then shorter versions of it: Commons search needs every word, so long queries find nothing
    ("Bondi Beach Sydney Australia summer beachgoers" -> "Bondi Beach Sydney Australia summer" -> ...)."""
    words = query.split()
    return [" ".join(words[:n]) for n in range(len(words), min(min_words, len(words)) - 1, -1)]


def find_photo(cache_root: Path, query: str, dest_stem: Path, *, avoid: set[str] = frozenset(),
               client: httpx.Client | None = None) -> tuple[Path, Photo] | None:
    """Search (cached), take the first photo not in `avoid` (titles), download it (cached). None if none fits."""
    cache = Cache(cache_root, "images")
    hits: list[dict] = []
    for q in _relaxed(query):
        skey = cache_key("commons-search", q.lower())
        found = cache.get_json(skey)
        if found is None:
            found = [asdict(p) for p in search_commons(q, client=client)]
            cache.put_json(skey, found)
        hits = [h for h in found if h["title"] not in avoid]
        if hits:
            break
    for raw in hits:
        photo = Photo(**raw)
        if photo.title in avoid:
            continue
        fkey = cache_key("commons-file", photo.url)
        name = "image" + _MIMES[photo.mime]
        cached = cache.get_files(fkey, [name])
        dest = dest_stem.with_suffix(_MIMES[photo.mime])
        if cached:
            dest.write_bytes(cached[0].read_bytes())
        else:
            dest = download(photo, dest_stem, client=client)
            cache.put_files(fkey, {name: dest})
        log.info("[images] %s -> %s (%s)", query, photo.title, photo.license)
        return dest, photo
    return None
