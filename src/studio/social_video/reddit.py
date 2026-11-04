"""Reddit story videos (r/nosleep and friends), in the "truyện Reddit" TikTok style.

  fetch      top posts of a subreddit via its RSS feed (Reddit's JSON API blocks scripts)
  translate  Vietnamese title + paragraphs -> vi.json (Claude, or free Google Translate)
  render     each sentence is voiced separately; a Reddit-style card shows the passage
             with the sentence being read highlighted; parts of <= part_max_sec over a
             parkour background with a quiet horror drone underneath
"""
from __future__ import annotations

import html
import math
import json
import random
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from . import bgclips, horrormusic, images, jumpscare, planner, tts
from .util import OUTPUT, FINAL_OUTPUT, ROOT, ffmpeg, log, media_duration, read_json, run, write_json

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
STORE = ROOT / "work" / "reddit"
DONE = OUTPUT / "reddit" / "done.json"

W, H = 1080, 1920
CARD_X, CARD_W, CARD_Y = 60, 960, 230
PAD = 40
SEAM = 960          # scene layout: photo above, gameplay below
GAP = 0.15            # even pause between sentences (engine silences are trimmed first)
FONTS = "C:/Windows/Fonts/"
COLORS = {"card": (14, 17, 19, 246), "border": (52, 62, 66, 255), "text": (242, 244, 245),
          "dim": (128, 138, 142), "meta": (130, 140, 145), "pill": (36, 44, 48, 255)}


# ---------------------------------------------------------------- fetch

def _paragraphs(content_html: str) -> list[str]:
    body = content_html.split("<!-- SC_ON -->")[0]
    parts = re.split(r"</p>|<br\s*/?>|</li>|</h\d>|<hr\s*/?>", body)
    out = []
    for p in parts:
        text = html.unescape(re.sub(r"<[^>]+>", "", p))
        text = re.sub(r"\s+", " ", text).strip()
        if text and not text.startswith("submitted by"):
            out.append(text)
    return out


def fetch(sub: str = "nosleep", period: str = "month", limit: int = 50,
          query: str = "") -> list[dict]:
    """Top posts of a subreddit, or with `query` its top search results (e.g. "rules")."""
    import requests
    from urllib.parse import quote_plus

    url = (f"https://www.reddit.com/r/{sub}/search.rss?q={quote_plus(query)}&restrict_sr=1"
           f"&sort=top&t={period}&limit={limit}" if query
           else f"https://www.reddit.com/r/{sub}/top/.rss?t={period}&limit={limit}")
    for attempt in range(5):
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.ok and r.content.strip():
            break
        time.sleep(6 * (attempt + 1))
    else:
        raise RuntimeError(f"Reddit RSS lỗi {r.status_code}")
    stories = []
    for e in ET.fromstring(r.content).findall("a:entry", ATOM):
        sid = e.find("a:id", ATOM).text.replace("t3_", "")
        paras = _paragraphs(e.find("a:content", ATOM).text or "")
        author = (e.find("a:author/a:name", ATOM).text or "").replace("/u/", "")
        story = {"id": sid, "sub": sub, "title": e.find("a:title", ATOM).text, "author": author,
                 "url": e.find("a:link", ATOM).get("href"),
                 "published": e.find("a:published", ATOM).text, "paragraphs": paras,
                 "words": sum(len(p.split()) for p in paras)}
        d = STORE / sid
        d.mkdir(parents=True, exist_ok=True)
        write_json(d / "source.json", story)
        stories.append(story)
    log(f"r/{sub} top {period}: {len(stories)} truyện")
    return stories


def fetch_post(sid: str, sub: str = "nosleep") -> dict:
    """One post by id (e.g. a later part of a series), via its comments RSS (first entry = post)."""
    import requests

    for attempt in range(5):
        try:
            r = requests.get(f"https://www.reddit.com/comments/{sid}/.rss", headers={"User-Agent": UA},
                             timeout=30)
            if r.ok and r.content.strip():
                break
        except requests.ConnectionError:
            r = None
        time.sleep(8 * (attempt + 1))
    else:
        raise RuntimeError(f"Reddit RSS lỗi {r and r.status_code}")
    e = ET.fromstring(r.content).findall("a:entry", ATOM)[0]
    paras = _paragraphs(e.find("a:content", ATOM).text or "")
    story = {"id": sid, "sub": sub, "title": e.find("a:title", ATOM).text,
             "author": (e.find("a:author/a:name", ATOM).text or "").replace("/u/", ""),
             "url": e.find("a:link", ATOM).get("href"), "published": e.find("a:updated", ATOM).text,
             "paragraphs": paras, "words": sum(len(p.split()) for p in paras)}
    (STORE / sid).mkdir(parents=True, exist_ok=True)
    write_json(STORE / sid / "source.json", story)
    return story


def _recorded_video(name: str) -> Path:
    path = Path(name)
    return path if path.is_absolute() else OUTPUT / path


def candidates(cfg: dict) -> list[dict]:
    """Stories not yet produced, short enough, and not later parts of a series."""
    done = read_json(DONE, {})
    rc = cfg["reddit"]
    out = []
    for f in sorted(STORE.glob("*/source.json")):
        s = read_json(f)
        recorded = done.get(s['id'], {}).get('files', [])
        available = bool(recorded) and all(_recorded_video(name).is_file() for name in recorded)
        if available or s["words"] > rc["max_words"] or s["words"] < 150:
            continue
        if re.search(r"\bpart\s*([2-9]|\d{2})\b|\[part|finale|update", s["title"], re.I):
            continue
        out.append(s)
    return sorted(out, key=lambda s: s["words"])


# ---------------------------------------------------------------- translation

TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"},
                   "paragraphs": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "paragraphs"],
    "additionalProperties": False,
}


def translate_prompt(story: dict) -> str:
    paras = "\n".join(f"[{i}] {p}" for i, p in enumerate(story["paragraphs"]))
    return f"""Dịch truyện kinh dị dưới đây (r/{story['sub']}, tác giả u/{story['author']}) sang tiếng Việt để
làm video đọc truyện. Văn kể chuyện tự nhiên, rùng rợn, ngôi thứ nhất "tôi" (giữ đúng ngôi của bản gốc),
câu ngắn vừa phải để đọc thành tiếng. Giữ nguyên tên riêng; đổi đơn vị đo sang hệ mét; số đếm nhỏ viết bằng chữ.
Không tóm tắt, không bỏ đoạn, không thêm lời bình. Bỏ các dòng không phải truyện (lời cảm ơn, link, "edit:").
Mỗi đoạn gốc thành một phần tử trong "paragraphs" (đúng thứ tự). "title": tiêu đề dịch, giữ độ gây tò mò.

Tiêu đề: {story['title']}

{paras}

Chỉ trả về JSON {{"title": "...", "paragraphs": ["...", ...]}}."""


def _google(text: str) -> str:
    import requests

    r = requests.get("https://translate.googleapis.com/translate_a/single",
                     params={"client": "gtx", "sl": "en", "tl": "vi", "dt": "t", "q": text},
                     headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return "".join(seg[0] for seg in r.json()[0] if seg[0])


def translate_google(story: dict) -> dict:
    """Free fallback: paragraphs batched under the endpoint's size limit."""
    out, batch = [], []

    def flush():
        if batch:
            joined = _google("\n\n".join(batch))
            got = [p.strip() for p in joined.split("\n\n")]
            out.extend(got if len(got) == len(batch) else [_google(p) for p in batch])
            batch.clear()

    for p in story["paragraphs"]:
        if sum(len(b) for b in batch) + len(p) > 3800:
            flush()
        batch.append(p)
    flush()
    return {"title": _google(story["title"]), "paragraphs": out}


def translate(story: dict, cfg: dict, backend: str) -> tuple[dict, str]:
    order = {"auto": ["api", "cli", "google"], "api": ["api"], "cli": ["cli"],
             "google": ["google"]}[backend]
    if backend == "auto" and not planner.has_api_key():
        order.remove("api")
    prompt = translate_prompt(story)
    for name in order:
        try:
            log(f"Dịch bằng: {name}")
            if name == "api":
                vi = planner.plan_with_api(prompt, cfg, TRANSLATE_SCHEMA)
            elif name == "cli":
                vi = planner.plan_with_cli(prompt, cfg)
            else:
                vi = translate_google(story)
            if vi.get("paragraphs"):
                return vi, name
        except Exception as exc:
            log(f"  {name} không dùng được: {exc}")
    raise RuntimeError("Không dịch được")


# ---------------------------------------------------------------- text layout

SENT_RE = re.compile(r"(?<=[.!?…])[\"”’»)]*\s+(?=[\"“‘«(]?[A-ZÀ-Ỹ0-9Đ\"“‘«(-])")


def sentences(paragraph: str) -> list[str]:
    parts = [p.strip() for p in SENT_RE.split(paragraph) if p and p.strip()]
    merged: list[str] = []
    for p in parts:   # glue tiny fragments ("Không." "Nó.") to their neighbour
        if merged and (len(p) < 14 or len(merged[-1]) < 14) and len(merged[-1]) + len(p) < 200:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged


def chunks(paragraphs: list[str], max_chars: int = 240) -> list[list[str]]:
    """Group sentences of one paragraph into card-sized passages."""
    out = []
    for para in paragraphs:
        cur: list[str] = []
        for s in sentences(para):
            if cur and (sum(len(x) for x in cur) + len(s) > max_chars or len(cur) >= 3):
                out.append(cur)
                cur = []
            cur.append(s)
        if cur:
            out.append(cur)
    return out


def caption_chunks(sentence: str, max_words: int = 6) -> list[str]:
    """A spoken sentence cut into short on-screen captions, at punctuation where possible."""
    out, cur = [], []
    for w in sentence.split():
        cur.append(w)
        if len(cur) >= max_words or (len(cur) >= 3 and w[-1] in ",.;:!?…\""):
            out.append(" ".join(cur))
            cur = []
    if cur:
        if out and len(cur) <= 2:
            out[-1] += " " + " ".join(cur)
        else:
            out.append(" ".join(cur))
    return out


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS + name, size)


def _wrap_words(draw, words: list[tuple[str, int]], font, width: int) -> list[list[tuple[str, int]]]:
    lines, cur, cur_w = [], [], 0.0
    space = draw.textlength(" ", font=font)
    for w, k in words:
        wl = draw.textlength(w, font=font)
        if cur and cur_w + space + wl > width:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur_w += (space if cur else 0) + wl
        cur.append((w, k))
    if cur:
        lines.append(cur)
    return lines


def _avatar(draw, x: int, y: int, r: int) -> None:
    """Round subreddit icon: dark disc with a crescent moon."""
    draw.ellipse([x, y, x + 2 * r, y + 2 * r], fill=(255, 69, 0))
    draw.ellipse([x + r * 0.45, y + r * 0.4, x + r * 1.55, y + r * 1.5], fill=(245, 245, 245))
    draw.ellipse([x + r * 0.75, y + r * 0.3, x + r * 1.75, y + r * 1.3], fill=(255, 69, 0))


class Cards:
    def __init__(self, story: dict, vi: dict, cfg: dict, outdir: Path):
        self.story, self.vi, self.cfg, self.dir = story, vi, cfg, outdir
        outdir.mkdir(parents=True, exist_ok=True)
        self.f_sub = _font("segoeuib.ttf", 34)
        self.f_meta = _font("segoeui.ttf", 30)
        self.f_title = _font("segoeuib.ttf", 54)
        self.f_body = _font("seguisb.ttf", 44)
        self.f_pill = _font("seguisb.ttf", 30)
        self.f_mark = _font("segoeuib.ttf", 34)
        self.f_caption = _font("segoeuib.ttf", 70)
        pub = datetime.fromisoformat(story["published"].replace("Z", "+00:00"))
        days = max(1, (datetime.now(timezone.utc) - pub).days)
        self.age = f"{days} ngày trước" if days < 30 else f"{days // 30} tháng trước"

    def _canvas(self, height: int):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([CARD_X, CARD_Y, CARD_X + CARD_W, CARD_Y + height], radius=30,
                            fill=COLORS["card"], outline=COLORS["border"], width=2)
        return im, d

    def _header(self, d, y: int, big: bool) -> int:
        r = 32 if big else 26
        _avatar(d, CARD_X + PAD, y, r)
        tx = CARD_X + PAD + 2 * r + 18
        sub = f"r/{self.story['sub']}"
        d.text((tx, y - 2), sub, font=self.f_sub, fill=COLORS["text"])
        d.text((tx + d.textlength(sub, font=self.f_sub) + 12, y + 2), f"• {self.age}",
               font=self.f_meta, fill=COLORS["meta"])
        d.text((tx, y + 38), f"u/{self.story['author']}", font=self.f_meta, fill=COLORS["meta"])
        return y + 2 * r + 34

    def _watermark(self, im) -> None:
        mark = self.cfg["reddit"]["watermark"]
        if mark:
            d = ImageDraw.Draw(im)
            tw = d.textlength(mark, font=self.f_mark)
            d.text((W - tw - 50, H - 330), mark, font=self.f_mark, fill=(255, 255, 255, 230),
                   stroke_width=3, stroke_fill=(0, 0, 0, 200))

    def title(self, name: str, part: int, parts: int) -> Path:
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        words = [(w, 0) for w in self.vi["title"].split()]
        lines = _wrap_words(probe, words, self.f_title, CARD_W - 2 * PAD)
        height = 34 + 98 + len(lines) * 68 + 40 + 64 + 36
        im, d = self._canvas(height)
        y = self._header(d, CARD_Y + 34, big=True)
        for line in lines:
            d.text((CARD_X + PAD, y), " ".join(w for w, _ in line), font=self.f_title,
                   fill=COLORS["text"])
            y += 68
        y += 30
        x = CARD_X + PAD
        labels = ["Upvote", "Bình luận", "Chia sẻ"] + ([f"Phần {part}/{parts}"] if parts > 1 else [])
        for i, label in enumerate(labels):
            tw = d.textlength(label, font=self.f_pill)
            extra = 34 if i == 0 else 0
            fill = (255, 69, 0, 255) if label.startswith("Phần") else COLORS["pill"]
            d.rounded_rectangle([x, y, x + tw + 44 + extra, y + 58], radius=29, fill=fill)
            if i == 0:   # upvote arrow
                d.polygon([(x + 22, y + 40), (x + 36, y + 16), (x + 50, y + 40)], fill=COLORS["text"])
            d.text((x + 22 + extra, y + 10), label, font=self.f_pill, fill=COLORS["text"])
            x += tw + 44 + extra + 16
        self._watermark(im)
        path = self.dir / f"{name}.png"
        im.save(path)
        return path

    def passage(self, name: str, sents: list[str], current: int) -> Path:
        words = [(w, k) for k, s in enumerate(sents) for w in s.split()]
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        lines = _wrap_words(probe, words, self.f_body, CARD_W - 2 * PAD)
        height = 30 + 86 + len(lines) * 60 + 30
        im, d = self._canvas(height)
        y = self._header(d, CARD_Y + 30, big=False) - 6
        space = d.textlength(" ", font=self.f_body)
        for line in lines:
            x = CARD_X + PAD
            for w, k in line:
                d.text((x, y), w, font=self.f_body,
                       fill=COLORS["text"] if k == current else COLORS["dim"])
                x += d.textlength(w, font=self.f_body) + space
            y += 60
        self._watermark(im)
        path = self.dir / f"{name}.png"
        im.save(path)
        return path

    def scene(self, name: str, photo: Path, caption: str) -> Path:
        """Split-screen frame: the scene photo fills the top half (the gameplay shows below),
        a small subreddit pill on it, and the caption in big type across the seam."""
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pic = Image.open(photo).convert("RGB")
        scale = max(W / pic.width, SEAM / pic.height)
        pic = pic.resize((round(pic.width * scale), round(pic.height * scale)), Image.LANCZOS)
        left, top = (pic.width - W) // 2, (pic.height - SEAM) // 2
        pic = pic.crop((left, top, left + W, top + SEAM))
        pic = ImageEnhance.Color(pic).enhance(0.75)
        pic = ImageEnhance.Brightness(ImageEnhance.Contrast(pic).enhance(1.08)).enhance(0.86)
        im.paste(pic, (0, 0))
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # blended over the photo, not pasted
        sd = ImageDraw.Draw(shade)
        fade = 220   # darken towards the seam so the caption reads on any photo
        for y in range(fade):
            sd.line([(0, SEAM - fade + y), (W, SEAM - fade + y)], fill=(0, 0, 0, int(170 * y / fade)))
        sub = f"r/{self.story['sub']}"
        tw = sd.textlength(sub, font=self.f_sub)
        sd.rounded_rectangle([36, 40, 36 + 76 + tw + 24, 40 + 64], radius=32, fill=(0, 0, 0, 170))
        im = Image.alpha_composite(im, shade)
        d = ImageDraw.Draw(im)
        _avatar(d, 46, 48, 24)
        d.text((36 + 76, 50), sub, font=self.f_sub, fill=COLORS["text"])
        lines = _wrap_words(d, [(w, 0) for w in caption.split()], self.f_caption, W - 120)
        y = SEAM + 40 - len(lines) * 88 / 2
        for line in lines:
            t = " ".join(w for w, _ in line)
            d.text(((W - d.textlength(t, font=self.f_caption)) / 2, y), t, font=self.f_caption,
                   fill=(255, 255, 255), stroke_width=9, stroke_fill=(0, 0, 0))
            y += 88
        self._watermark(im)
        path = self.dir / f"{name}.png"
        im.save(path)
        return path

    def hook(self, name: str, text: str) -> Path:
        """Opening line in big type over a darkened frame; the last sentence in red."""
        im = Image.new("RGBA", (W, H), (0, 0, 0, 150))
        d = ImageDraw.Draw(im)
        font = _font("segoeuib.ttf", 78)
        sents = sentences(text) or [text]
        words = [(w, int(k == len(sents) - 1 and len(sents) > 1))
                 for k, s in enumerate(sents) for w in s.split()]
        lines = _wrap_words(d, words, font, W - 160)
        y = H * 0.42 - len(lines) * 98 / 2
        for line in lines:
            t = " ".join(w for w, _ in line)
            x = (W - d.textlength(t, font=font)) / 2
            for w, red in line:
                d.text((x, y), w, font=font, fill=(255, 52, 40) if red else (255, 255, 255),
                       stroke_width=5, stroke_fill=(0, 0, 0))
                x += d.textlength(w + " ", font=font)
            y += 98
        path = self.dir / f"{name}.png"
        im.save(path)
        return path

    def end(self, name: str, text: str) -> Path:
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        lines = _wrap_words(probe, [(w, 0) for w in text.split()], self.f_title, CARD_W - 2 * PAD)
        height = 50 + len(lines) * 68 + 40
        im, d = self._canvas(height)
        y = CARD_Y + 45
        for line in lines:
            t = " ".join(w for w, _ in line)
            d.text((CARD_X + (CARD_W - d.textlength(t, font=self.f_title)) / 2, y), t,
                   font=self.f_title, fill=COLORS["text"])
            y += 68
        self._watermark(im)
        path = self.dir / f"{name}.png"
        im.save(path)
        return path


# ---------------------------------------------------------------- audio

def _tcfg(cfg: dict) -> dict:
    return {**cfg["tts"], "wait_quota": cfg["reddit"]["wait_for_vivibe"]}


def voice_all(texts: list[str], audio_dir: Path, cfg: dict,
              role: str = "narrator_female") -> list[tuple[Path, float]]:
    return tts.voice_sentences(texts, audio_dir, _tcfg(cfg), GAP, [role] * len(texts))


def voice_free(text: str, audio_dir: Path, cfg: dict, role: str) -> tuple[Path, float]:
    """One line in the free voices only (edge/gTTS), cached under a hash of its text, so
    editing a hook re-voices it and the paid quota is never touched."""
    import hashlib

    key = hashlib.sha1(f"{role}|{text}".encode("utf-8")).hexdigest()[:12]
    tcfg = _tcfg(cfg)
    tcfg = {**tcfg, "engines": [e for e in tcfg["engines"] if e in ("vieneu", "edge", "gtts")]}
    return tts.voice_sentences([text], audio_dir / key, tcfg, GAP, [role])[0]


# ---------------------------------------------------------------- dialogue voices

QUOTE_RE = re.compile(r'"[^"]*(?:"|$)|“[^”]*(?:”|$)')
SPEECH_VERB = re.compile(r"(?<!\w)(nói|hỏi|đáp|bảo|hét|gào|thét|thì thầm|thì thào|lẩm bẩm|kêu|gọi|"
                         r"quát|thốt|rít|nức nở|trả lời|lên tiếng|chen vào|cười|thở dài|van|"
                         r"nài|gắt|rên|lắp bắp|thông báo|nhắc|dặn|khẳng định)(?!\w)")
# who a pronoun in the attribution points to -> generic role, mapped per story by cast
CUES = [
    ("child", ("con bé", "cô bé", "thằng bé", "cậu bé", "đứa bé", "đứa trẻ", "thằng nhóc")),
    ("old_male", ("ông lão", "ông già", "ông cụ", "ông nội", "ông ngoại")),
    ("old_female", ("bà lão", "bà già", "bà cụ", "bà nội", "bà ngoại")),
    ("female", ("cô ấy", "cô ta", "bà ấy", "bà ta", "chị ấy", "chị ta", "người phụ nữ", "mẹ",
                "vợ", "em gái", "chị", "bà", "cô")),
    ("male", ("anh ấy", "anh ta", "ông ấy", "ông ta", "cậu ấy", "cậu ta", "người đàn ông",
              "anh trai", "hắn", "gã", "bố", "chồng", "thầy", "chú", "ông", "cậu", "anh")),
]


def _has(win: str, cue: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(cue)}(?!\w)", win, re.I) is not None


def _attributed(paragraph: str, cast: dict) -> str | None:
    """Speaker of the quotes in a paragraph, from the words just before a speech verb
    ("…," vợ tôi hỏi / Mark nói / tôi đáp), or any character name in the narration."""
    attr = QUOTE_RE.sub(" ", paragraph)
    names = cast.get("names", {})
    for m in SPEECH_VERB.finditer(attr):
        win = " ".join(attr[max(0, m.start() - 40):m.start()].split()[-3:])
        for name, role in names.items():
            if name in win:
                return role
        for generic, cues in CUES:
            if any(_has(win, c) for c in cues):
                return cast.get(generic, generic)
        if _has(win, "tôi") or _has(win, "mình"):
            return "narrator"
    for name, role in names.items():
        if name in attr:
            return role
    return None


def _subject(text: str, cast: dict) -> str | None:
    """Who an action line is about, from its first words ("Vợ tôi đưa tay…" -> female)."""
    win = " ".join(text.split()[:4])
    for name, role in cast.get("names", {}).items():
        if name in win:
            return role
    for generic, cues in CUES:
        if any(_has(win, c) for c in cues):
            return cast.get(generic, generic)
    if _has(win, "tôi"):
        return "narrator"
    return None


def speakers(paragraphs: list[str], cast: dict) -> list[str | None]:
    """Role per paragraph: None for plain narration, else who says its quotes.

    Order of evidence: vi["cast"]["speakers"] overrides by paragraph index, a speech verb
    in the paragraph ("…," vợ tôi hỏi), the subject of a short action line just before
    ("Vợ tôi đưa tay lên che miệng." then a quote), and finally alternation between the
    narrator and the last other speaker, which short action lines do not interrupt.
    """
    overrides = {int(k): v for k, v in cast.get("speakers", {}).items()}
    out: list[str | None] = []
    last_other = cast.get("other", "male")
    prev: str | None = None          # speaker of the running exchange
    beat: str | None = None          # subject of the action line right before
    for i, para in enumerate(paragraphs):
        if not QUOTE_RE.search(para):
            out.append(None)
            beat = _subject(para, cast) if len(para) < 220 else None
            if len(para) >= 220:     # a real narration passage ends the exchange
                prev = None
            continue
        who = overrides.get(i) or _attributed(para, cast)
        if who is None:
            who = beat or (last_other if prev in (None, "narrator") else "narrator")
            # a name called out inside the quote is who is spoken TO, never the speaker
            spoken = " ".join(QUOTE_RE.findall(para))
            addressed = {r for n, r in cast.get("names", {}).items() if n in spoken}
            if who in addressed:
                who = "narrator" if who != "narrator" else last_other
        if who != "narrator":
            last_other = who
        out.append(who)
        prev, beat = who, None
    return out


def _segments(sentence: str, start: int, quotes: list[tuple[int, int]]) -> list[tuple[str, bool]]:
    """Split one sentence (at `start` in its paragraph) into (text, is_quote) pieces."""
    end = start + len(sentence)
    cuts = sorted({start, end} | {x for a, b in quotes for x in (a, b) if start < x < end})
    pieces = []
    for a, b in zip(cuts, cuts[1:]):
        text = sentence[a - start:b - start].strip(' "“”')
        inside = any(qa <= a < qb for qa, qb in quotes)
        if re.search(r"\w", text):
            pieces.append((text, inside))
    return pieces or [(sentence, False)]


def voice_story(paragraphs: list[str], cfg: dict, cast: dict,
                audio_dir: Path) -> list[tuple[Path, float]]:
    """One wav per sentence, narration in the narrator's voice and quotes in the
    speaker's: pieces are voiced separately (grouped by role) and joined per sentence."""
    import hashlib
    signature = hashlib.sha256(json.dumps([paragraphs, cast, cfg['tts']], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    audio_dir = audio_dir / signature
    audio_dir.mkdir(parents=True, exist_ok=True)
    narrator = cast.get("narrator", "narrator_female")
    roles_of = speakers(paragraphs, cast)
    items: list[tuple[str, str]] = []
    owner: list[list[int]] = []          # sentence -> its item indexes
    for para, who in zip(paragraphs, roles_of):
        quotes = [(m.start(), m.end()) for m in QUOTE_RE.finditer(para)]
        cursor = 0
        for group in chunks([para]):
            for sent in group:
                at = para.find(sent, cursor)
                at = cursor if at < 0 else at
                cursor = at + len(sent)
                idx = []
                for text, inside in _segments(sent, at, quotes):
                    role = narrator if (not inside or who in (None, "narrator")) else who
                    idx.append(len(items))
                    items.append((text, role))
                owner.append(idx)
    pieces = tts.voice_sentences([t for t, _ in items], audio_dir / "pieces", _tcfg(cfg), 0.04,
                                 [r for _, r in items])
    out = []
    for k, idx in enumerate(owner):
        wav = audio_dir / f"s{k:04d}.wav"
        if not wav.exists():
            _join([pieces[i][0] for i in idx], wav, GAP - 0.04)
        out.append((wav, media_duration(wav)))
    return out


def _join(wavs: list[Path], out: Path, tail: float) -> None:
    import wave

    frames, params = [], None
    for w in wavs:
        with wave.open(str(w)) as fh:
            params = params or fh.getparams()
            frames.append(fh.readframes(fh.getnframes()))
    silence = b"\0" * (int(params.framerate * tail) * params.sampwidth * params.nchannels)
    with wave.open(str(out), "wb") as fh:
        fh.setparams(params)
        fh.writeframes(b"".join(frames) + silence)


def _drone() -> Path:
    """Copyright-free dark ambience: low brown noise + slow-beating low tones."""
    path = ROOT / "cache" / "horror_drone.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.6:duration=90",
             "-f", "lavfi", "-i", "sine=frequency=55:duration=90",
             "-f", "lavfi", "-i", "sine=frequency=58.3:duration=90",
             "-filter_complex",
             "[0]lowpass=f=260,volume=0.35[n];[1]volume=0.5[a];[2]volume=0.45[b];"
             "[n][a][b]amix=inputs=3:normalize=0,tremolo=f=0.15:d=0.5,"
             "afade=in:d=3,afade=out:st=87:d=3",
             "-ac", "2", "-ar", "48000", str(path)])
    return path


# ---------------------------------------------------------------- render

def _slug(text: str, n: int = 50) -> str:
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "-", text).lower()[:n].strip("-") or "truyen"


def _number_vi(n: int) -> str:
    return ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín", "mười"][n] \
        if n <= 10 else str(n)


def render(story_id: str, cfg: dict) -> list[Path]:
    d = STORE / story_id
    story, vi = read_json(d / "source.json"), read_json(d / "vi.json")
    if not vi:
        raise SystemExit(f"Chưa có {d / 'vi.json'} (bản dịch).")
    rc = cfg["reddit"]
    groups = chunks([p for p in vi["paragraphs"] if p.strip()])
    flat = [s for g in groups for s in g]
    log(f"Truyện {story_id}: {len(flat)} câu, {len(groups)} thẻ, "
        f"{sum(len(s) for s in flat)} ký tự")

    # Vivibe's hourly export quota is waited out (one voice per story); other Vivibe
    # failures fall back to the free voices inside tts.
    # voice every sentence (cached, so re-renders are free); vi["cast"] names the
    # narrator's voice and who speaks the dialogue
    cast = vi.get("cast", {})
    paragraphs = [p for p in vi["paragraphs"] if p.strip()]
    voiced = voice_story(paragraphs, cfg, cast, d / "audio")
    budget = rc["part_max_sec"] - 9   # title + ending cards

    # split into parts at passage boundaries, as evenly as possible: as few parts as the
    # budget allows, each cut at the boundary nearest to an equal share (no 15 s tail)
    spans, k = [], 0
    for g in groups:
        spans.append(((g, k), sum(dur for _, dur in voiced[k:k + len(g)])))
        k += len(g)
    total = sum(t for _, t in spans)
    n_target = max(1, math.ceil(total / budget))
    while True:
        parts, cur, cur_t, done_t = [], [], 0.0, 0.0
        for item, t in spans:
            share = (total - done_t) / max(1, n_target - len(parts))   # what each remaining part gets
            over = cur_t + t > budget
            past = cur and len(parts) < n_target - 1 and abs(cur_t + t - share) > abs(cur_t - share)
            if cur and (over or past):
                parts.append(cur)
                done_t += cur_t
                cur, cur_t = [], 0.0
            cur.append(item)
            cur_t += t
        if cur:
            parts.append(cur)
        if len(parts) <= n_target:
            break
        n_target += 1   # a long passage forced an extra cut: re-balance with one more part
    n_parts = len(parts)

    cards = Cards(story, vi, cfg, d / "cards")
    # a shocking title and spoken hook (vi["shock_title"], vi["hook"]) open every part
    title_text = (vi.get("shock_title") or vi["title"]).strip()
    hook = (vi.get("hook") or "").strip()
    narrator = cast.get("narrator", "narrator_female")
    # vi["continues"]: this file holds only the first part of a longer story
    last = "Còn tiếp ở phần sau." if vi.get("continues") else "Hết truyện."
    end_texts = [f"Còn tiếp ở phần {_number_vi(i + 2)}." for i in range(n_parts - 1)] + [last]
    if hook:   # extra lines in the free voices, cached by text
        hook_voice = voice_free(hook, d / "audio_hook", cfg, narrator)
        intro = [voice_free(f"Phần {_number_vi(i + 1)}.", d / "audio_hook", cfg, narrator)
                 if n_parts > 1 else None for i in range(n_parts)]
        endings = [voice_free(t, d / "audio_hook", cfg, narrator) for t in end_texts]
    else:      # old style: the title read out
        intro_texts = ([f"{title_text}. Phần {_number_vi(i + 1)}." for i in range(n_parts)]
                       if n_parts > 1 else [title_text])
        extra = voice_all(intro_texts + end_texts, d / "audio_extra", cfg, narrator)
        intro, endings = extra[:n_parts], extra[n_parts:]
    faces, screams, stings = jumpscare.faces(), jumpscare.screams(), jumpscare.stings()
    rng = random.Random(story_id)
    # vi["scenes"] {"paragraph index": "English photo query"}: the split-screen layout, a photo
    # found online for each scene above the gameplay; stories without it keep the Reddit cards
    scenes = sorted((int(i), q) for i, q in (vi.get("scenes") or {}).items())
    para_of, k = {}, 0   # first sentence of a passage -> its paragraph
    for pi, para in enumerate(paragraphs):
        for g in chunks([para]):
            para_of[k] = pi
            k += len(g)

    def photo_for(k0: int) -> Path | None:
        queries = [q for i, q in scenes if i <= para_of.get(k0, 0)] or [scenes[0][1]]
        return images.find(queries[-1], d / "img")

    day = date.today().isoformat()
    from studio.core.outputs import organized_output
    outdir = organized_output(FINAL_OUTPUT, 'reddit', d/'output_location.json')
    outdir.mkdir(parents=True, exist_ok=True)
    slug = _slug(title_text)
    made = []
    for p, part in enumerate(parts):
        timeline: list[tuple[Path, Path | None, float]] = []   # (card png, audio wav, seconds)
        if hook:
            wav, dur = hook_voice
            timeline.append((cards.hook(f"hook_{p}", hook), wav, dur + 0.35))
            wav, dur = intro[p] or (None, 0.0)
            timeline.append((cards.title(f"title_{p}", p + 1, n_parts), wav,
                             max(dur + 0.3, 1.4)))
        else:
            wav, dur = intro[p]
            timeline.append((cards.title(f"title_{p}", p + 1, n_parts), wav, dur + 0.25))
        sents = [(g, k0, j) for g, k0 in part for j in range(len(g))]
        scare = jumpscare.moment([g[j] for g, _, j in sents]) if faces and screams else None
        scare_at = None
        for i, (g, k0, j) in enumerate(sents):
            wav, dur = voiced[k0 + j]
            photo = photo_for(k0) if scenes else None
            if photo:   # the sentence as short captions, each on screen for its share of the line
                caps = caption_chunks(g[j])
                weights = [len(c) + 4 for c in caps]
                card = [(cards.scene(f"s{k0:04d}_{j}_{c}", photo, cap), wgt / sum(weights))
                        for c, (cap, wgt) in enumerate(zip(caps, weights))]
            else:
                card = cards.passage(f"c{k0:04d}_{j}", g, j)
            timeline.append((card, wav, dur))
            if i == scare:   # right after the line: flash + face frames, then a beat of quiet
                scare_at = sum(t for _, _, t in timeline)
                timeline += [(png, None, t) for png, t in jumpscare.frames(rng.choice(faces))]
                timeline.append((card[-1][0] if isinstance(card, list) else card, None, 0.25))
        wav, dur = endings[p]
        end_text = (("Còn tiếp…" if vi.get("continues") else "Hết truyện") if p == n_parts - 1
                    else f"Còn tiếp ở phần {p + 2}…")
        timeline.append((cards.end(f"end_{p}", end_text), wav, dur + 0.6))

        tag = f"part{p + 1}"
        card_list = d / f"{tag}_cards.txt"
        lines = []
        for png, _, t in timeline:   # a captioned line is a list of (frame, share of its time)
            for frame, share in (png if isinstance(png, list) else [(png, 1.0)]):
                lines += [f"file '{frame.as_posix()}'", f"duration {t * share:.3f}"]
        lines.append(f"file '{timeline[-1][0].as_posix()}'")
        card_list.write_text("ffconcat version 1.0\n" + "\n".join(lines) + "\n", encoding="utf-8")
        audio_list = d / f"{tag}_audio.txt"
        audio_lines = []
        # one audio file per slot; slots without a voice (jumpscare frames) are merged into
        # a single run of silence
        slots: list[tuple[Path | None, float]] = []
        for _, wav, t in timeline:
            if wav is None and slots and slots[-1][0] is None:
                slots[-1] = (None, slots[-1][1] + t)
            else:
                slots.append((wav, t))
        for i, (wav, t) in enumerate(slots):
            if wav is None or media_duration(wav) < t - 0.02:   # slot longer than its voice
                padded = d / f"{tag}_slot{i}.wav"
                src = (["-i", str(wav)] if wav
                       else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
                run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *src, "-af", "apad",
                     "-t", f"{t:.3f}", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le",
                     str(padded)])
                wav = padded
            audio_lines.append(f"file '{wav.as_posix()}'")
        audio_list.write_text("ffconcat version 1.0\n" + "\n".join(audio_lines) + "\n",
                              encoding="utf-8")
        narration = d / f"{tag}_narration.wav"
        run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", audio_list.name, "-c:a", "pcm_s16le", narration.name], cwd=d)
        total = media_duration(narration)

        out = outdir / (f"reddit__{story_id}__{slug}_p{p + 1}.mp4" if n_parts > 1 else f"reddit__{story_id}__{slug}.mp4")
        # rendered in three runs (picture, sound, mux): one graph with both stalls ffmpeg
        speed = max(1.0, total / 179.5)   # Shorts stop at 3 minutes: speed up the rare long part
        length = total / speed

        # picture: 0 cards (jumpscare frames included), 1 one gameplay video from a random point
        v_in = ["-f", "concat", "-safe", "0", "-i", card_list.name]
        bg = bgclips.pick(total, rng, W / (H - SEAM) if scenes else W / H)
        if bg:
            src, start, crop = bg
            v_in += ["-stream_loop", "-1", "-ss", f"{start:.2f}", "-an", "-i", str(src)]
            clip = f"trim=duration={total + 0.5:.2f},setpts=PTS-STARTPTS"
            if scenes:   # sharp gameplay below the photo, the same footage blurred behind the top
                vchain = (f"[1:v]{crop}fps=30,scale={W}:{H - SEAM},setsar=1,{clip},split[g1][g2];"
                          f"[g2]boxblur=24:2,eq=brightness=-0.3[gb];[gb][g1]vstack[bg];")
            else:
                vchain = f"[1:v]{crop}fps=30,scale={W}:{H},setsar=1,{clip}[bg];"
        else:
            v_in += ["-f", "lavfi", "-i", f"color=c=0x101418:s={W}x{H}:r=30"]
            vchain = "[1:v]setsar=1[bg];"
        vchain += ("[0:v]format=rgba,fps=30[cards];[bg][cards]overlay=0:0:format=auto,format=yuv420p"
                   + (f",setpts=PTS/{speed:.4f}" if speed > 1 else "") + "[v]")
        picture = d / f"{tag}_picture.mp4"
        run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *v_in,
             "-filter_complex", vchain, "-map", "[v]", "-t", f"{length:.3f}", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", picture.name], cwd=d)

        # sound: 0 narration, 1 music, then the hook sting and the scream
        a_in = ["-i", narration.name]
        music = horrormusic.tracks() if rc.get("music_volume", 0) > 0 else []
        if music:
            # horror score from a random point, ducked under the voice so every word stays clear
            track = rng.choice(music)
            a_in += ["-stream_loop", "-1", "-ss",
                     f"{rng.uniform(0, max(0.0, media_duration(track) - 20)):.2f}",
                     "-i", str(track)]
            mix = (f"[0:a]asplit=2[nar][key];[1:a]volume={rc['music_volume']}[mus];"
                   "[mus][key]sidechaincompress=threshold=0.015:ratio=5:attack=20:release=450[duck];")
        else:
            a_in += ["-stream_loop", "-1", "-i", str(_drone())]
            mix = f"[1:a]volume={rc['ambience_volume']}[duck];[0:a]anull[nar];"
        labels = "[nar][duck]"
        if hook and stings:   # suspense sting under the opening hook
            a_in += ["-i", str(rng.choice(stings))]
            t0 = timeline[0][2]
            mix += (f"[{a_in.count('-i') - 1}:a]atrim=0:{t0:.2f},"
                    f"afade=out:st={max(0.5, t0 - 0.6):.2f}:d=0.6,volume=0.45[st];")
            labels += "[st]"
        if scare_at is not None:
            a_in += ["-i", str(rng.choice(screams))]
            mix += f"[{a_in.count('-i') - 1}:a]adelay={int(scare_at * 1000)}:all=1[sc];"
            labels += "[sc]"
        mix += (f"{labels}amix=inputs={labels.count('[')}:duration=first:normalize=0"
                + (f",atempo={speed:.4f}" if speed > 1 else "") + "[a]")
        sound = d / f"{tag}_sound.wav"
        run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *a_in,
             "-filter_complex", mix, "-map", "[a]", "-t", f"{length:.3f}",
             "-c:a", "pcm_s16le", sound.name], cwd=d)

        draft = d / f'{tag}_unmastered.mp4'
        run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", picture.name,
             "-i", sound.name, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
             "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(draft)], cwd=d)
        from .quality import publish
        publish(draft, out, cfg)
        picture.unlink(missing_ok=True)
        sound.unlink(missing_ok=True)
        made.append(out)
        log(f"  → {out.name} ({length:.0f}s"
            + (f", jumpscare {scare_at:.0f}s" if scare_at is not None else "") + ")")

    titles = outdir / "titles.txt"
    with titles.open("a", encoding="utf-8") as fh:
        for p, out in enumerate(made):
            suffix = f" (Phần {p + 1}/{n_parts})" if n_parts > 1 else ""
            fh.write(f"{title_text}{suffix}\t{out.name}\tTruyện gốc: u/{story['author']} – "
                     f"r/{story['sub']} – {story['url']}\n")
    done = read_json(DONE, {})
    done[story_id] = {"title": title_text, "files": [str(m.resolve()) for m in made]}
    write_json(DONE, done)
    return made


def prep(story_id: str) -> Path:
    """Write the manual translation request (for Claude Code) next to the story."""
    d = STORE / story_id
    story = read_json(d / "source.json")
    path = d / "translate_request.md"
    path.write_text(translate_prompt(story), encoding="utf-8")
    return path


def auto(cfg: dict, count: int, translator: str) -> list[Path]:
    made = []
    for _ in range(count):
        todo = candidates(cfg)
        if not todo:
            fetch(cfg["reddit"]["sub"], cfg["reddit"]["period"])
            todo = candidates(cfg)
        if not todo:
            log("Hết truyện phù hợp.")
            break
        story = todo[0]
        d = STORE / story["id"]
        if not (d / "vi.json").exists():
            vi, used = translate(story, cfg, translator)
            write_json(d / "vi.json", vi)
            log(f"Đã dịch ({used}): {vi['title']}")
        made += render(story["id"], cfg)
    return made


def list_json(cfg: dict) -> str:
    return json.dumps([{k: s[k] for k in ("id", "words", "title")} for s in candidates(cfg)],
                      ensure_ascii=False, indent=1)
