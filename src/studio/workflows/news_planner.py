"""Scene planner for news videos: script beats -> scene plans.

A beat is one idea of the voice-over with a role (hook, quote, fact, number, document, timeline, closing). The
shared layout config (assets/shared/layouts/news.yaml) maps the role to a layout. The planner then

- picks the asset the layout wants from the classified media (portrait / document / editorial photo), never
  showing a portrait outside a quote and preferring a different photo when a new idea starts;
- checks every number, date and name the layout puts on screen against the article text, and drops or replaces
  what it cannot verify (another layout, the article title, no title line), recording why;
- records per scene: role, layout, the spoken line, on-screen text, asset (path, origin, credit) or the
  fallback used and its reason, the crop focus point and the minimum hold.

Scene count, topic, numbers and length all come from the script; only the rules live in the config.
"""

from __future__ import annotations

import re
import unicodedata

from ..core.config import load_yaml
from ..core.project import ProjectContext
from ..providers.source.article import Article

ROLES = ("hook", "quote", "fact", "number", "document", "timeline", "closing")
# v1 scripts (type headline | photo | quote | stat | card) still load
OLD_TYPES = {"headline": "hook", "photo": "fact", "quote": "quote", "stat": "number", "card": "document"}
DEFAULT_CONFIG = "asset:shared/layouts/news.yaml"
TEXT_FIELDS = ("headline", "highlight", "category", "kicker", "name", "title", "value", "unit", "explain",
               "image_query")


def load_layout_config(ctx: ProjectContext) -> dict:
    o = ctx.project.options
    cfg = load_yaml(ctx.resolve(str(o.get("layout_config") or DEFAULT_CONFIG), what="layout config"))
    theme = dict(cfg.get("theme") or {})
    if o.get("accent"):
        theme["accent"] = str(o["accent"])
    cfg["theme"] = theme
    return cfg


def normalize_beat(b: dict) -> dict:
    """A beat with every field present; v1 beats (`type`, `role` = person title, label/note) are mapped."""
    beat = {k: str(b.get(k) or "").strip() for k in TEXT_FIELDS}
    role = str(b.get("role") or "").strip()
    if b.get("type") in OLD_TYPES and role not in ROLES:
        beat["title"] = beat["title"] or role
        role = OLD_TYPES[b["type"]]
        beat["unit"] = beat["unit"] or str(b.get("label") or "").strip()
        beat["explain"] = beat["explain"] or str(b.get("note") or "").strip()
    beat["role"] = role if role in ROLES else "fact"
    beat["narration"] = " ".join(str(b.get("narration", "")).split())
    image = b.get("image", -1)
    beat["image"] = image if isinstance(image, int) else -1
    beat["points"] = [" ".join(str(p).split()) for p in b.get("points") or [] if str(p).strip()]
    beat["dates"] = [{"date": str(d.get("date", "")).strip(), "text": " ".join(str(d.get("text", "")).split())}
                     for d in b.get("dates") or [] if isinstance(d, dict) and str(d.get("date", "")).strip()]
    return beat


# ------------------------------------------------------------------ media classes


def person_caption(caption: str) -> tuple[str, str]:
    """("PGS. TS Nguyễn Hoàng Hải", "Phó Giám đốc ...") from a portrait caption "Name - Title." """
    head, sep, tail = caption.partition(" - ")
    return (head.strip(), tail.strip(" .")) if sep and len(head.split()) <= 8 else ("", "")


def classify_media(media: list[dict], cfg: dict) -> list[str | None]:
    """portrait | document | editorial per media entry (None when the file is unusable). media.json `kind` wins."""
    words = [w.lower() for w in (cfg.get("classify") or {}).get("document", [])]
    kinds: list[str | None] = []
    for m in media:
        if not m.get("path"):
            kinds.append(None)
        elif m.get("kind") in ("portrait", "document", "editorial"):
            kinds.append(m["kind"])
        elif person_caption(m.get("caption") or "")[0]:
            kinds.append("portrait")
        elif any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", (m.get("caption") or "").lower()) for w in words):
            kinds.append("document")
        else:
            kinds.append("editorial")
    return kinds


# ------------------------------------------------------------------ fact checks

_VI_MONTHS = {"một": 1, "giêng": 1, "hai": 2, "ba": 3, "tư": 4, "bốn": 4, "năm": 5, "sáu": 6, "bảy": 7, "tám": 8,
              "chín": 9, "mười": 10, "mười một": 11, "mười hai": 12, "chạp": 12}
_NUM_RE = re.compile(r"\d+(?:[.,:/]\d+)*")
_HONORIFIC = re.compile(r"^(?:(?:gs|pgs|ts|ths|bs|ks|ls|ns|tsk?h)\.?\s*|ông\s+|bà\s+|anh\s+|chị\s+)+", re.I)


def corpus(art: Article) -> str:
    """The article text the screen may quote: title, lead, body, photo captions. "tháng năm" -> "tháng 5"."""
    text = "\n".join([art.title, art.lead, *art.paragraphs, *(im.caption for im in art.images)])
    for word in sorted(_VI_MONTHS, key=len, reverse=True):
        text = re.sub(rf"(?i)\btháng {word}\b", f"tháng {_VI_MONTHS[word]}", text)
    return unicodedata.normalize("NFC", text)


def unverified_numbers(text: str, source: str) -> list[str]:
    """Numbers in `text` that the article does not contain ("12.000" also matches "12000"; "15.3" matches the
    date "15.3.2021", "15/3" and "15-3")."""
    bad = []
    for num in _NUM_RE.findall(text):
        forms = {num, num.replace(".", ""), num.replace(",", "."), num.replace(".", ","), num.replace("/", "."),
                 num.replace(".", "/"), num.replace(".", "-")}
        ok = any(re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d]|[.,/-]\d{{3}})", source) or
                 re.search(rf"(?<![\d.,]){re.escape(f)}[./-]\d{{2,4}}(?!\d)", source) for f in forms)
        if not ok:
            bad.append(num)
    return bad


def _initialisms(source: str) -> set[str]:
    """"Đại học Quốc gia Hà Nội" -> ĐHQG, ĐHQGHN, QGHN...: abbreviations of capitalised runs in the article."""
    out: set[str] = set()
    for run in re.findall(r"(?:[A-ZĐÀ-Ỹ][\wÀ-ỹ]*\s+(?:[a-zà-ỹđ]+\s+)?){2,8}", source):
        words = run.split()
        letters = [w[0].upper() for w in words]
        for i in range(len(letters)):
            for j in range(i + 2, len(letters) + 1):
                out.add("".join(letters[i:j]))
    return out


def name_verified(name: str, source: str) -> bool:
    """The person's name (without PGS./TS/ông...) appears in the article; titles in the name are not checked."""
    core = _HONORIFIC.sub("", name.strip()).strip()
    return bool(core) and core.lower() in source.lower()


def title_verified(title: str, source: str) -> bool:
    """At least 80% of the title's words (or their abbreviations, ĐHQG) are in the article."""
    words = re.findall(r"[\wÀ-ỹ]+", title)
    if not words:
        return True
    have = {w.lower() for w in re.findall(r"[\wÀ-ỹ]+", source)}
    abbr = {a.lower() for a in _initialisms(source)}
    hit = sum(1 for w in words if w.lower() in have or w.lower() in abbr)
    return hit / len(words) >= 0.8 and not unverified_numbers(title, source)


# ------------------------------------------------------------------ planning


def _credit_chip(m: dict | None, art: Article, lang: str) -> str:
    if not m:
        return ""
    if m.get("origin") == "commons":
        who = " · ".join(x for x in (m.get("author"), m.get("license"), "Wikimedia Commons") if x)
        return ("Ảnh minh họa: " if lang == "vi" else "Illustration: ") + who
    who = m.get("credit") if m.get("credit") and m.get("credit") != "own" else art.publisher
    return (f"Nguồn: ảnh {who}" if lang == "vi" else f"Photo: {who}") if who else ""


def source_line(art: Article, lang: str) -> str:
    parts = [p for p in (art.publisher, art.date_label) if p]
    return ("Nguồn: " if lang == "vi" else "Source: ") + " · ".join(parts) if parts else ""


def reading_hold(layout: str, text: dict, cfg: dict) -> float | None:
    """Minimum screen time for reading; voice duration can make the scene longer, never shorter."""
    motion = cfg.get("motion") or {}
    base = (motion.get("min_hold_sec") or {}).get("document" if layout == "text_card" else layout)
    if layout == "stat_card":
        content = " ".join(str(text.get(k) or "") for k in ("kicker", "value", "unit", "explain"))
    elif layout == "timeline":
        content = str(text.get("title") or "") + " ".join(
            f"{d['date']} {d['text']}" for d in text.get("items") or [])
    elif layout == "text_card":
        content = str(text.get("title") or "") + " ".join(text.get("points") or [])
    else:
        return base
    chars_per_sec = max(1, float(motion.get("reading_chars_per_sec", 18)))
    return round(max(float(base or 0), len(content.strip()) / chars_per_sec + 0.7), 2)


def plan_scenes(beats: list[dict], media: list[dict], art: Article, cfg: dict, *, lang: str = "vi") -> list[dict]:
    kinds = classify_media(media, cfg)
    src = corpus(art)
    roles_map = cfg.get("roles") or {}
    layouts = cfg.get("layouts") or {}
    uses: dict[int, int] = {}
    plans: list[dict] = []
    prev_fg: int | None = None  # asset shown sharp in the previous scene

    def usable(kind: str) -> list[int]:
        return [i for i, k in enumerate(kinds) if k == kind]

    def pick(kind: str, wanted: int, *, query_for: int | None = None, avoid: int | None = None) -> int | None:
        """The beat's own image when it is of that class, else its Commons photo, else the least used one
        (article photos before illustrations), avoiding the previous scene's photo while there is a choice."""
        pool = [i for i in usable(kind) if media[i].get("origin") != "commons"
                or (query_for is not None and media[i].get("for_beat") == query_for)]
        if kind == "document":
            pool = [i for i in pool if media[i].get("verified") is True]
        if not pool:
            return None
        if wanted in pool and (wanted != avoid or len(pool) == 1):
            return wanted
        own = [i for i in pool if query_for is not None and media[i].get("for_beat") == query_for]
        if own and own[0] != avoid:
            return own[0]
        cands = [i for i in pool if i != avoid] or pool
        return min(cands, key=lambda i: (uses.get(i, 0), media[i].get("origin") == "commons", i))

    for n, beat in enumerate(beats):
        role = beat["role"]
        layout = roles_map.get(role, "editorial_photo")
        notes: list[str] = []
        fallback: str | None = None
        text: dict = {}
        asset: int | None = None

        if layout == "headline":
            head = beat["headline"] or art.title
            if unverified_numbers(head, src):
                notes.append(f"headline number(s) {unverified_numbers(head, src)} not in the article -> "
                             f"article title")
                head = art.title
            hl = beat["highlight"] if beat["highlight"] and beat["highlight"].lower() in head.lower() else ""
            if beat["highlight"] and not hl:
                notes.append("highlight phrase is not part of the headline -> none")
            text = {"headline": head, "highlight": hl, "category": beat["category"] or art.section or ""}
            asset = pick("editorial", beat["image"], query_for=n)
            if asset is None:
                fallback = "no documentary photo: headline over a dark backdrop"
        elif layout == "portrait_quote":
            name = beat["name"]
            if not name or not name_verified(name, src):
                notes.append(f"speaker '{name}' not named in the article -> photo layout")
                layout = "editorial_photo"
            else:
                title = beat["title"]
                if title and not title_verified(title, src):
                    notes.append(f"title '{title}' not in the article -> name only")
                    title = ""
                text = {"name": name, "title": title}
                match = [i for i in usable("portrait")
                         if name_verified(person_caption(media[i].get("caption") or "")[0] or "-", name)
                         or _HONORIFIC.sub("", name).strip().lower() in (media[i].get("caption") or "").lower()]
                cands = sorted(match, key=lambda i: i != beat["image"])
                asset = cands[0] if cands else None
                if asset is None:
                    fallback = "no portrait of the speaker in the article: name bar over the backdrop"
        elif layout == "stat_card":
            value = beat["value"]
            if not value or unverified_numbers(value, src):
                notes.append(f"number '{value}' not in the article -> photo layout")
                layout = "editorial_photo"
            else:
                explain = beat["explain"]
                if unverified_numbers(explain, src):
                    notes.append(f"explain line has unverified number(s) {unverified_numbers(explain, src)} -> "
                                 f"dropped")
                    explain = ""
                text = {"value": value, "unit": beat["unit"], "explain": explain, "kicker": beat["kicker"]}
                asset = pick("editorial", beat["image"], query_for=n)
        elif layout == "timeline":
            items = [d for d in beat["dates"] if not unverified_numbers(f"{d['date']} {d['text']}", src)]
            dropped = len(beat["dates"]) - len(items)
            if dropped:
                notes.append(f"{dropped} milestone(s) with unverified dates dropped")
            max_items = int(layouts.get("timeline", {}).get("max_items", 4))
            if len(items) < 2:
                notes.append("fewer than 2 verified milestones -> photo layout")
                layout = "editorial_photo"
            else:
                text = {"title": beat["headline"] or beat["kicker"], "items": items[:max_items]}
                asset = pick("editorial", beat["image"], query_for=n)
        elif layout == "document":
            points = [p for p in beat["points"] if not unverified_numbers(p, src)]
            if len(points) < len(beat["points"]):
                notes.append(f"{len(beat['points']) - len(points)} point(s) with unverified numbers dropped")
            doc = pick("document", beat["image"])
            if doc is not None:
                asset = doc
                text = {"kicker": beat["kicker"]}
            elif points:
                fallback = "no verified document image (cover/poster) in the source: text guide card"
                layout = "text_card"
                text = {"kicker": beat["kicker"] or ("Thông tin chính" if lang == "vi" else "Key points"),
                        "title": beat["headline"], "points": points[:int(layouts.get("document", {})
                                                                         .get("max_points", 4))],
                        "source": source_line(art, lang)}
                asset = pick("editorial", beat["image"], query_for=n)
            else:
                notes.append("no document image and no verified points -> photo layout")
                layout = "editorial_photo"
        elif layout == "closing":
            line = beat["headline"]
            if unverified_numbers(line, src):
                notes.append("closing line has unverified numbers -> dropped")
                line = ""
            text = {"headline": line, "highlight": beat["highlight"] if beat["highlight"] and
                    beat["highlight"].lower() in line.lower() else "", "source": source_line(art, lang)}
            asset = pick("editorial", beat["image"], query_for=n, avoid=prev_fg)

        if layout == "editorial_photo":  # also the target of every downgrade above
            text = {"kicker": beat["kicker"]}
            asset = pick("editorial", beat["image"], query_for=n, avoid=prev_fg)
            if asset is not None and asset == prev_fg:
                notes.append("only one documentary photo for two ideas in a row: same photo, different motion")
            if asset is None:
                fallback = "no documentary photo: dark backdrop"

        m = media[asset] if asset is not None else None
        params = layouts.get("document" if layout == "text_card" else layout) or {}
        sharp = layout in ("headline", "portrait_quote", "editorial_photo", "document")
        # the subject point of the photo (media.json `focus`, set after looking at it) beats the layout default
        focus = (m.get("focus") if m else None) or params.get("focus") or [0.5, 0.45]
        kb = params.get("ken_burns", "zoom_in")
        if isinstance(kb, list):
            kb = kb[n % len(kb)]
        if sharp and asset is not None and asset == prev_fg and plans and kb == plans[-1]["ken_burns"]:
            kb = "pan_right" if kb != "pan_right" else "pan_left"  # same photo again: at least move differently
        if asset is not None:
            uses[asset] = uses.get(asset, 0) + (1 if sharp else 0)
        prev_fg = asset if sharp else None
        plans.append({
            "role": role, "layout": layout, "narration": beat["narration"], "text": text,
            "asset": ({"index": asset, "path": m["path"], "kind": kinds[asset], "origin": m.get("origin", "article"),
                       "credit": m.get("credit"), "caption": m.get("caption"), "page": m.get("page") or m.get("src")}
                      if m else None),
            # photo credit on sharp photos; the article source on number cards (cards and closing print it)
            "chip": _credit_chip(m, art, lang) if sharp else
                    (source_line(art, lang) if layout in ("stat_card", "timeline") else ""),
            "fallback": fallback, "notes": notes, "focus": [round(float(f), 3) for f in focus],
            "ken_burns": kb, "min_hold_sec": reading_hold(layout, text, cfg),
        })
    return plans
