"""Content sources: pasted text, generic URL, Reddit (official OAuth API), Threads (official Graph API).

Everything is normalized to a `SourcePost` and saved as <project>/source/source.json.
No scraping of logged-in pages, no cookies: if an official API is not configured, paste the text.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx

from ...core.errors import ProviderUnavailable, ValidationError

UA = "windows:video-short-studio:0.1"


@dataclass
class SourcePost:
    platform: str
    title: str
    body: str = ""
    url: str | None = None
    author: str | None = None
    community: str | None = None
    score: int | None = None
    comments: list[dict] = field(default_factory=list)  # [{author, body, score}]
    language: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    nsfw: bool = False

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SourcePost:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def credit(self) -> str:
        who = f"u/{self.author}" if self.platform == "reddit" and self.author else (self.author or "")
        where = f"r/{self.community}" if self.platform == "reddit" and self.community else (self.community or "")
        parts = [p for p in (where, who) if p]
        return f"Source: {self.platform} {' · '.join(parts)}".strip() + (f" — {self.url}" if self.url else "")


# ------------------------------------------------------------------ manual text


def from_text_file(path: Path, platform: str = "manual") -> SourcePost:
    """First line starting with '# ' (or the first line) is the title, the rest is the body."""
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ValidationError(f"{path} is empty", code="empty_source")
    lines = text.splitlines()
    title = lines[0].lstrip("#").strip()
    body = "\n".join(lines[1:]).strip()
    meta: dict[str, str] = {}
    # optional front-matter style lines: "url: ...", "author: ...", "community: ..."
    keep = []
    for ln in body.splitlines():
        m = re.match(r"^(url|author|community|platform|score):\s*(.+)$", ln.strip(), re.I)
        if m and not keep:
            meta[m.group(1).lower()] = m.group(2).strip()
        else:
            keep.append(ln)
    body = "\n".join(keep).strip()
    score = int(meta["score"]) if meta.get("score", "").isdigit() else None
    return SourcePost(platform=meta.get("platform", platform), title=title, body=body, url=meta.get("url"),
                      author=meta.get("author"), community=meta.get("community"), score=score)


# ------------------------------------------------------------------ generic URL


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form"}

    def __init__(self):
        super().__init__()
        self.title = ""
        self.paras: list[str] = []
        self._skip = 0
        self._in_title = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "li", "h1", "h2", "h3", "blockquote"):
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in ("p", "li", "h1", "h2", "h3", "blockquote") and not self._skip:
            t = " ".join("".join(self._buf).split())
            if len(t) > 30:
                self.paras.append(t)
            self._buf = []

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._buf.append(data)


def from_url(url: str, *, max_comments: int = 5, cache_dir: Path | None = None) -> SourcePost:
    if re.search(r"(^|\.)reddit\.com/|redd\.it/", url):
        return reddit_post(url, max_comments=max_comments)
    if re.search(r"threads\.(net|com)/", url):
        return threads_post(url, cache_dir)
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderUnavailable(f"cannot fetch {url}: {e}", code="source_offline") from e
    p = _TextExtractor()
    p.feed(r.text)
    if not p.paras:
        raise ProviderUnavailable(f"no readable text found at {url} - paste it into source/source.md",
                                  code="source_manual")
    return SourcePost(platform=httpx.URL(url).host, title=p.title.strip() or url, body="\n\n".join(p.paras[:60]),
                      url=url)


# ------------------------------------------------------------------ Reddit (official OAuth API)

_token_cache: dict[str, str] = {}


def _reddit_token() -> str:
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        raise ProviderUnavailable(
            "Reddit API not configured (REDDIT_CLIENT_ID/SECRET in .env). Paste the post into source/source.md "
            "instead.", code="source_no_key")
    if "t" in _token_cache:
        return _token_cache["t"]
    try:
        r = httpx.post("https://www.reddit.com/api/v1/access_token", auth=(cid, secret),
                       data={"grant_type": "client_credentials"}, headers={"User-Agent": _reddit_ua()}, timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderUnavailable(f"Reddit auth failed: {e}", code="source_auth") from e
    _token_cache["t"] = r.json()["access_token"]
    return _token_cache["t"]


def _reddit_ua() -> str:
    return os.environ.get("REDDIT_USER_AGENT") or UA


def _reddit_get(path: str, params: dict | None = None) -> dict | list:
    try:
        r = httpx.get(f"https://oauth.reddit.com{path}", params=params,
                      headers={"Authorization": f"bearer {_reddit_token()}", "User-Agent": _reddit_ua()}, timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderUnavailable(f"Reddit API error: {e}", code="source_api") from e
    return r.json()


def reddit_post_id(url: str) -> str:
    m = re.search(r"/comments/([a-z0-9]+)", url) or re.search(r"redd\.it/([a-z0-9]+)", url)
    if not m:
        raise ValidationError(f"not a Reddit post URL: {url}", code="bad_url")
    return m.group(1)


def reddit_post(url: str, *, max_comments: int = 5) -> SourcePost:
    pid = reddit_post_id(url)
    data = _reddit_get(f"/comments/{pid}", {"limit": max_comments * 3, "sort": "top", "raw_json": 1})
    post = data[0]["data"]["children"][0]["data"]
    comments = []
    for c in data[1]["data"]["children"]:
        cd = c.get("data", {})
        if c.get("kind") != "t1" or cd.get("stickied") or cd.get("body") in (None, "[deleted]", "[removed]"):
            continue
        comments.append({"author": cd.get("author"), "body": cd.get("body", ""), "score": cd.get("score")})
        if len(comments) >= max_comments:
            break
    return SourcePost(platform="reddit", title=post["title"], body=post.get("selftext", ""),
                      url=f"https://www.reddit.com{post['permalink']}", author=post.get("author"),
                      community=post.get("subreddit"), score=post.get("score"), comments=comments,
                      nsfw=bool(post.get("over_18")))


def reddit_discover(subreddit: str, *, period: str = "day", limit: int = 15, allow_nsfw: bool = False,
                    min_chars: int = 200) -> list[dict]:
    data = _reddit_get(f"/r/{subreddit}/top", {"t": period, "limit": limit, "raw_json": 1})
    out = []
    for c in data["data"]["children"]:
        d = c["data"]
        if d.get("over_18") and not allow_nsfw:
            continue
        if d.get("stickied"):
            continue
        out.append({
            "id": d["id"], "title": d["title"], "score": d.get("score"), "comments": d.get("num_comments"),
            "chars": len(d.get("selftext", "")), "url": f"https://www.reddit.com{d['permalink']}",
            "text_post": bool(d.get("is_self")), "enough_text": len(d.get("selftext", "")) >= min_chars,
        })
    return out


# ------------------------------------------------------------------ Threads (official Graph API)


def threads_discover(query: str, *, limit: int = 15, search_type: str = "TOP") -> list[dict]:
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    if not token:
        raise ProviderUnavailable("THREADS_ACCESS_TOKEN not set in .env (needs threads_keyword_search permission)",
                                  code="source_no_key")
    try:
        r = httpx.get("https://graph.threads.net/v1.0/keyword_search",
                      params={"q": query, "search_type": search_type, "limit": limit,
                              "fields": "id,text,username,permalink,timestamp", "access_token": token}, timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        # httpx puts the request URL (with access_token) in the message: report the status only
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else type(e).__name__
        raise ProviderUnavailable(f"Threads API error: {status}", code="source_api") from None
    return [{"id": d.get("id"), "title": (d.get("text") or "")[:90], "author": d.get("username"),
             "url": d.get("permalink"), "chars": len(d.get("text") or ""), "text": d.get("text"),
             "timestamp": d.get("timestamp")}
            for d in r.json().get("data", [])]


def _threads_key(url: str) -> str:
    """threads.net and threads.com permalinks of one post map to the same key (/@user/post/<code>)."""
    return httpx.URL(url.strip()).path.rstrip("/")


def _threads_cache(cache_dir: Path) -> Path:
    return cache_dir / "threads" / "posts.json"


def save_threads_posts(cache_dir: Path, posts: list[dict]) -> int:
    """Remember discover results (text from the official API) so `--url <permalink>` can use them later."""
    f = _threads_cache(cache_dir)
    known = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    n = 0
    for p in posts:
        if p.get("url") and p.get("text"):
            known[_threads_key(p["url"])] = {k: p.get(k) for k in ("id", "url", "author", "text", "timestamp")}
            n += 1
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(known, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)
    return n


def threads_post(url: str, cache_dir: Path | None) -> SourcePost:
    """A Threads post found earlier by `studio discover threads`; the API has no fetch-by-permalink."""
    f = _threads_cache(cache_dir) if cache_dir else None
    hit = (json.loads(f.read_text(encoding="utf-8")) if f and f.is_file() else {}).get(_threads_key(url))
    if not hit:
        raise ProviderUnavailable(
            "this Threads post is not in the discover cache - run `studio discover threads <query>` "
            "(THREADS_ACCESS_TOKEN in .env) to find it first, or paste the text into source/source.md",
            code="source_manual")
    text = str(hit.get("text") or "").strip()
    first, _, rest = text.partition("\n")
    if rest.strip() and len(first) <= 90:  # same rule as pasted text: first line is the title
        title, body = first.strip(), rest.strip()
    else:
        title, body = f"@{hit.get('author') or 'threads'}", text
    return SourcePost(platform="threads", title=title, body=body, url=hit.get("url") or url,
                      author=hit.get("author"))
