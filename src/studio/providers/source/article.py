"""News articles: one page the user points at (URL, saved .html or pasted markdown) -> `Article`.

Read from the page's own metadata (Open Graph, JSON-LD NewsArticle) and its <article> body. One plain request per
URL the user gives; a bot-check page (JS cookie challenge, captcha) is never worked around - the user saves the
page from their browser instead (Ctrl+S, "Web page, HTML only") or pastes the text.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from ...core.errors import ProviderUnavailable, ValidationError
from . import UA

# "Ảnh: Thanh Chân." / "Ảnh minh hoạ: NTCC" / "Photo: Reuters" at the end of a caption
CREDIT_RE = re.compile(r"[\s.(-]*(?:Ảnh(?: minh ho[ạa])?|Nguồn(?: ảnh)?|Photo|Image|Source)\s*:\s*([^.()]+?)[.)]?\s*$",
                       re.I)
BLOCKED_RE = re.compile(r"document\.cookie|location\.reload|captcha|cf-chl|challenge-platform|Just a moment", re.I)


@dataclass
class ArticleImage:
    src: str  # absolute URL or a path (project-relative, or relative to the saved page)
    caption: str = ""
    credit: str = ""


@dataclass
class Article:
    title: str
    lead: str = ""
    paragraphs: list[str] = field(default_factory=list)
    url: str | None = None
    publisher: str | None = None
    section: str | None = None
    published: str | None = None  # ISO date/time as the page gives it
    author: str | None = None
    images: list[ArticleImage] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Article:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        data["images"] = [ArticleImage(**i) for i in data.get("images", [])]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def date_label(self) -> str:
        """27/01/2021 from an ISO timestamp (or the text as given)."""
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", self.published or "")
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (self.published or "")

    def credit(self) -> str:
        bits = [b for b in (self.publisher, self.author, self.date_label) if b]
        return f"Nguồn: {' · '.join(bits)}" + (f" — {self.url}" if self.url else "")


def split_credit(caption: str) -> tuple[str, str]:
    """("Bài thi mẫu sẽ được công bố.", "Thanh Chân") from "... Ảnh minh hoạ: Thanh Chân." """
    caption = " ".join(caption.split())
    m = CREDIT_RE.search(caption)
    if not m:
        return caption, ""
    text = caption[: m.start()].strip(" .-")
    return (f"{text}." if text else ""), m.group(1).strip()


# ------------------------------------------------------------------ HTML


class _ArticleParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "form", "nav", "footer", "aside", "button"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.ld: list[str] = []
        self.title = ""
        self.h1 = ""
        self.paras: list[tuple[str, bool, int]] = []  # (text, inside <article>, parent element id)
        self.figures: list[dict] = []
        self._stack: list[tuple[str, int]] = []
        self._next_id = 0
        self._skip = 0
        self._article = 0
        self._cap: list[str] | None = None
        self._p: list[str] | None = None
        self._p_parent = 0
        self._fig: dict | None = None
        self._in = ""  # title | h1 | ld

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            key = a.get("property") or a.get("name") or a.get("itemprop")
            if key and a.get("content") and key not in self.meta:
                self.meta[key.lower()] = unescape(a["content"]).strip()
            return
        if tag in ("img", "source", "br", "link", "input", "hr", "wbr"):
            if tag == "img" and self._fig is not None and not self._skip:
                src = a.get("data-src") or a.get("data-original") or _best_srcset(a.get("srcset", "")) \
                    or a.get("src", "")
                if src and not src.startswith("data:") and not self._fig.get("src"):
                    self._fig["src"] = src
            return
        self._next_id += 1
        self._stack.append((tag, self._next_id))
        if tag in self.SKIP:
            self._skip += 1
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in = "ld"
            self.ld.append("")
        elif tag == "title":
            self._in = "title"
        elif tag == "h1" and not self.h1:
            self._in = "h1"
        elif tag == "article":
            self._article += 1
        elif tag == "figure" and not self._skip:
            self._fig = {"src": "", "caption": "", "in_article": self._article > 0}
        elif tag == "figcaption" and self._fig is not None:
            self._cap = []
        elif tag == "p" and not self._skip and self._cap is None:
            self._p = []
            self._p_parent = self._stack[-2][1] if len(self._stack) > 1 else 0

    def handle_endtag(self, tag):
        while self._stack:  # tolerate unclosed tags: pop up to the matching start tag
            t, _ = self._stack.pop()
            if t in self.SKIP and self._skip:
                self._skip -= 1
            if t == tag:
                break
        if tag in ("script", "title", "h1") and self._in:
            self._in = ""
        elif tag == "article" and self._article:
            self._article -= 1
        elif tag == "figcaption" and self._cap is not None and self._fig is not None:
            self._fig["caption"] = " ".join("".join(self._cap).split())
            self._cap = None
        elif tag == "figure" and self._fig is not None:
            if self._fig.get("src"):
                self.figures.append(self._fig)
            self._fig = None
        elif tag == "p" and self._p is not None:
            text = " ".join("".join(self._p).split())
            if len(text) > 30:
                self.paras.append((text, self._article > 0, self._p_parent))
            self._p = None

    def handle_data(self, data):
        if self._in == "ld":
            self.ld[-1] += data
        elif self._in == "title":
            self.title += data
        elif self._in == "h1":
            self.h1 += data
        if self._skip:
            return
        if self._cap is not None:
            self._cap.append(data)
        elif self._p is not None:
            self._p.append(data)


def _best_srcset(srcset: str) -> str:
    items = [s.strip().split() for s in srcset.split(",") if s.strip()]
    return items[-1][0] if items else ""


def _ld_article(blobs: list[str]) -> dict:
    """The NewsArticle/Article object from JSON-LD blocks (lists and @graph included)."""
    for blob in blobs:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if not isinstance(item, dict):
                continue
            stack += item.get("@graph", []) if isinstance(item.get("@graph"), list) else []
            kind = item.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(k in ("NewsArticle", "Article", "ReportageNewsArticle", "BlogPosting") for k in kinds):
                return item
    return {}


def _name(v) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("name", "")
    v = str(v or "").strip()
    return "" if v.startswith("http") else v


def _same_image(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.netloc + pa.path).lower() == (pb.netloc + pb.path).lower()


def parse_article_html(html: str, base_url: str | None = None) -> Article:
    p = _ArticleParser()
    p.feed(html)
    m, ld = p.meta, _ld_article(p.ld)
    title = (_name(ld.get("headline")) or m.get("og:title") or " ".join(p.h1.split()) or " ".join(p.title.split()))
    if not title:
        raise ValidationError("no article title found in the page", code="empty_source")
    in_article = [(t, pid) for t, inside, pid in p.paras if inside]
    if in_article:
        paras = [t for t, _ in in_article]
    else:  # no <article>: the parent element holding the most paragraph text is the body
        totals: dict[int, int] = {}
        for t, _, pid in p.paras:
            totals[pid] = totals.get(pid, 0) + len(t)
        best = max(totals, key=totals.get) if totals else None
        paras = [t for t, _, pid in p.paras if pid == best]
    lead = " ".join((m.get("og:description") or _name(ld.get("description")) or m.get("description") or "").split())
    if paras and lead and (paras[0].startswith(lead[:60]) or lead.startswith(paras[0][:60])):
        first = paras.pop(0)  # the sapo is also the first body paragraph: keep the complete one as the lead
        lead = first if len(first) >= len(lead) else lead
    elif paras and not lead:
        lead = paras.pop(0)
    url = m.get("og:url") or base_url
    images: list[ArticleImage] = []
    figs = [f for f in p.figures if f["caption"] and (f["in_article"] or not any(x["in_article"] for x in p.figures))]
    for f in figs:
        src = urljoin(base_url or url or "", unescape(f["src"]))
        caption, credit = split_credit(f["caption"])
        if not any(_same_image(src, i.src) for i in images):
            images.append(ArticleImage(src=src, caption=caption, credit=credit))
    og = m.get("og:image")
    if og:
        og = urljoin(base_url or url or "", og)
        if not any(_same_image(og, i.src) for i in images):
            images.insert(0, ArticleImage(src=og))
    host = urlparse(url or "").netloc.removeprefix("www.")
    return Article(
        title=" ".join(title.split()), lead=lead, paragraphs=paras, url=url,
        publisher=m.get("og:site_name") or _name(ld.get("publisher")) or host or None,
        section=m.get("article:section") or _name(ld.get("articleSection")) or None,
        published=m.get("article:published_time") or _name(ld.get("datePublished")) or None,
        author=_name(ld.get("author")) or _name(m.get("author")) or None,
        images=images,
    )


def article_from_url(url: str) -> Article:
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderUnavailable(f"cannot fetch {url}: {e}", code="source_offline") from e
    if len(r.text) < 3000 and BLOCKED_RE.search(r.text):
        raise ProviderUnavailable(
            f"{urlparse(url).netloc} answered with a bot-check page instead of the article. Open it in your "
            "browser, press Ctrl+S -> 'Web page, HTML only', and save it as source/article.html "
            "(or paste the text into source/source.md)", code="source_blocked")
    art = parse_article_html(r.text, str(r.url))
    if not art.paragraphs and not art.lead:
        raise ProviderUnavailable(f"no article text found at {url} - save the page as source/article.html",
                                  code="source_manual")
    return art


# ------------------------------------------------------------------ pasted markdown


MD_META_RE = re.compile(r"^(url|publisher|section|published|date|author|image)\s*:\s*(.+)$", re.I)


def article_from_markdown(text: str) -> Article:
    """`# Title`, then optional `key: value` lines (url, publisher, section, published, author and repeatable
    `image: <url or path> | caption`), then the lead paragraph and the body."""
    lines = text.strip().splitlines()
    if not lines or not lines[0].strip():
        raise ValidationError("source is empty", code="empty_source")
    title = lines[0].lstrip("#").strip()
    meta: dict[str, str] = {}
    images: list[ArticleImage] = []
    rest: list[str] = []
    in_meta = True
    for ln in lines[1:]:
        mm = MD_META_RE.match(ln.strip()) if in_meta else None
        if mm:
            key, value = mm.group(1).lower(), mm.group(2).strip()
            if key == "image":
                src, _, cap = value.partition("|")
                caption, credit = split_credit(cap.strip())
                images.append(ArticleImage(src=src.strip(), caption=caption, credit=credit))
            else:
                meta["published" if key == "date" else key] = value
        elif ln.strip() or not in_meta:
            in_meta = False
            rest.append(ln)
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", "\n".join(rest)) if p.strip()]
    return Article(title=title, lead=paras[0] if paras else "", paragraphs=paras[1:], url=meta.get("url"),
                   publisher=meta.get("publisher"), section=meta.get("section"), published=meta.get("published"),
                   author=meta.get("author"), images=images)


def looks_like_html(text: str) -> bool:
    head = text.lstrip()[:500].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<head" in head
