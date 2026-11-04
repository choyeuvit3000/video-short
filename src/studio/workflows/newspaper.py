"""N1 newspaper: a news article (URL, saved page or pasted text) -> a short news video.

Stages: article -> news_script -> news_media -> news_scenes -> (validate, voice, render, qc, package)
  article     : source/article.json from source/article.html (page saved from the browser), source/source.md
                (pasted markdown, or a saved page given with --text-file) or project.source.url (one request)
  news_script : work/script.json - beats (headline | photo | quote | stat | card) written by an AI CLI, or built
                from the article text when no CLI answers (options.rewrite=auto)
  news_media  : the article's photos downloaded to work/news/ (or your own files in images/), credited
  news_scenes : a still (Ken Burns) + a static text overlay per beat, project.json scenes
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
from PIL import Image

from ..core.errors import ManualGateRequired, ProviderUnavailable, ValidationError
from ..core.logging_utils import get_logger
from ..core.project import ProjectContext
from ..core.schema import Scene, VisualSpec
from ..core.textnorm import clean_for_speech
from ..providers.llm import generate_json
from ..providers.source import UA
from ..providers.source.article import (
    Article,
    article_from_markdown,
    article_from_url,
    looks_like_html,
    parse_article_html,
)
from ..renderers.news import news_overlay, still_backdrop, still_card, still_framed, still_photo
from . import fill, load_workflow, read_prompt
from .story_reader import WORDS_PER_SEC, story_sentences

log = get_logger()

BEAT_TYPES = ("headline", "photo", "quote", "stat", "card")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
MAX_IMAGE_BYTES = 15 * 1024 * 1024
LANG_NAME = {"vi": "Vietnamese (tiếng Việt, natural spoken news style)", "en": "English (natural spoken news style)"}
CHIP = {"vi": "Nguồn: ảnh {who}", "en": "Photo: {who}"}

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "upload title, max 90 characters"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(BEAT_TYPES)},
                    "narration": {"type": "string", "description": "spoken text, 1-2 short sentences"},
                    "image": {"type": "integer", "description": "index into the image list, -1 for none"},
                    "headline": {"type": "string", "description": "headline beat: max 60 characters"},
                    "category": {"type": "string", "description": "headline beat: 1-2 words"},
                    "name": {"type": "string", "description": "quote beat: who is speaking"},
                    "role": {"type": "string", "description": "quote beat: their title"},
                    "value": {"type": "string", "description": "stat beat: the number, max 8 characters"},
                    "label": {"type": "string", "description": "stat beat: what it counts, max 4 words"},
                    "note": {"type": "string", "description": "stat beat: small line under the label"},
                },
                "required": ["type", "narration", "image", "headline", "category", "name", "role", "value",
                             "label", "note"],
            },
        },
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "beats", "description", "hashtags"],
}


def _empty_beat(kind: str, narration: str, image: int = -1, **kw: str) -> dict:
    beat = {"type": kind, "narration": narration, "image": image, "headline": "", "category": "", "name": "",
            "role": "", "value": "", "label": "", "note": ""}
    beat.update(kw)
    return beat


# ------------------------------------------------------------------ stage: article


MANUAL_SOURCE = (
    "### Source article\n\n"
    "Give the article in one of these ways:\n\n"
    "1. Open it in your browser, press **Ctrl+S**, choose **Web page, HTML only**, save it as `source/article.html`.\n"
    "2. Or paste it into `source/source.md`:\n\n"
    "```\n# Article title\nurl: https://...\npublisher: Lao Động\nsection: Giáo dục\npublished: 2021-01-27\n"
    "image: https://.../photo.jpg | Caption. Ảnh: Photographer\n\nLead paragraph (sapo)...\n\nBody...\n```\n\n"
    "3. Or set `source.url` in project.json (works for sites without a bot check).\n"
)


def stage_article(ctx: ProjectContext, opts: dict) -> str:
    out = ctx.dir / "source" / "article.json"
    if out.exists() and not opts.get("force"):
        return "existing source/article.json"
    p = ctx.project
    html_file, md = ctx.dir / "source" / "article.html", ctx.dir / "source" / "source.md"
    if html_file.exists():
        art, how = parse_article_html(html_file.read_text(encoding="utf-8-sig", errors="replace"), p.source.url), \
            "saved page"
    elif md.exists():
        text = md.read_text(encoding="utf-8-sig", errors="replace")
        art, how = (parse_article_html(text, p.source.url), "saved page") if looks_like_html(text) \
            else (article_from_markdown(text), "pasted text")
    elif p.source.url:
        try:
            art, how = article_from_url(p.source.url), "url"
        except ProviderUnavailable as e:
            raise ManualGateRequired("article", f"{e}\n\n{MANUAL_SOURCE}") from e
    else:
        raise ManualGateRequired("article", MANUAL_SOURCE)
    if not art.paragraphs and not art.lead:
        raise ValidationError("the article has no text", code="empty_source")
    art.url = art.url or p.source.url
    art.save(out)
    p.source.type = ("url" if how == "url" else "manual") if p.source.type == "none" else p.source.type
    p.source.platform, p.source.url, p.source.author = art.publisher, art.url, art.author
    p.source.title, p.source.community = art.title, art.section
    p.source.credit_text = p.source.credit_text or art.credit()
    ctx.save()
    chars = len(art.lead) + sum(len(x) for x in art.paragraphs)
    return f"{how}: {art.publisher or '-'} · {chars} chars, {len(art.paragraphs)} paragraphs, {len(art.images)} images"


# ------------------------------------------------------------------ stage: news_script


def _person(caption: str) -> tuple[str, str]:
    """("PGS. TS Nguyễn Hoàng Hải", "Phó Giám đốc ...") from a portrait caption "Name - Role." """
    head, sep, tail = caption.partition(" - ")
    return (head.strip(), tail.strip(" .")) if sep and len(head.split()) <= 8 else ("", "")


def _passthrough(art: Article, opts: dict, lang: str) -> dict:
    """Beats straight from the article text: headline + lead, then 1-2 sentence beats until target_sec."""
    target = float(opts.get("target_sec", 50))
    n_img = len(art.images)
    people = [(i, *_person(im.caption)) for i, im in enumerate(art.images) if _person(im.caption)[0]]
    beats = [_empty_beat("headline", art.lead or art.title, 0 if n_img else -1, headline=art.title,
                         category=art.section or "")]
    spent = len((art.lead or art.title).split()) / WORDS_PER_SEC[lang]
    chunks: list[str] = []
    for para in art.paragraphs:
        cur = ""
        for s in story_sentences(para):
            if cur and (len(cur) + len(s) > 220 or cur.count(". ") >= 1):
                chunks.append(cur)
                cur = s
            else:
                cur = f"{cur} {s}".strip()
        if cur:
            chunks.append(cur)
    k = 1
    for text in chunks:
        sec = len(text.split()) / WORDS_PER_SEC[lang]
        if spent + sec > target and len(beats) > 1:
            break
        spent += sec
        quoted = next(((i, name, role) for i, name, role in people
                       if re.search(r"[\"“”]", text) and name.split()[-1] in text), None)
        if quoted:
            beats.append(_empty_beat("quote", text, quoted[0], name=quoted[1], role=quoted[2]))
        else:
            beats.append(_empty_beat("photo", text, (k % n_img) if n_img else -1))
            k += 1
    return {"title": art.title, "beats": beats, "description": art.lead[:280], "hashtags": [], "source": "passthrough"}


def _llm_script(ctx: ProjectContext, art: Article, opts: dict, force: bool) -> dict:
    p = ctx.project
    target = int(opts.get("target_sec", 50))
    images = "\n".join(f"[{i}] {im.caption or '(no caption)'}" for i, im in enumerate(art.images)) or "(none)"
    prompt = fill(read_prompt(ctx.settings, "newspaper", "script.md"), {
        "language": LANG_NAME[p.language],
        "target_sec": target,
        "max_words": int(target * WORDS_PER_SEC[p.language]),
        "beats": int(opts.get("beats", 7)),
        "publisher": art.publisher or "-",
        "section": art.section or "-",
        "published": art.date_label or "-",
        "title": art.title,
        "lead": art.lead or "-",
        "body": "\n\n".join(art.paragraphs) or "-",
        "images": images,
    })
    wf = load_workflow(ctx.settings, "newspaper")
    data, provider = generate_json(ctx, "news_script", prompt, SCRIPT_SCHEMA, chain=wf.get("llm_chain"), force=force)
    data["source"] = provider
    return data


def _check_script(data: dict, n_images: int) -> dict:
    beats = []
    for b in data.get("beats", []):
        kind = b.get("type") if b.get("type") in BEAT_TYPES else "photo"
        narration = " ".join(str(b.get("narration", "")).split())
        if not narration:
            continue
        image = b.get("image", -1)
        image = image if isinstance(image, int) and 0 <= image < n_images else -1
        if kind == "quote" and not b.get("name"):
            kind = "photo"
        if kind == "stat" and not b.get("value"):
            kind = "photo"
        beats.append({**_empty_beat(kind, narration, image), **{k: str(b.get(k) or "").strip() for k in
                                                                ("headline", "category", "name", "role", "value",
                                                                 "label", "note")}})
    if not beats:
        raise ValidationError("script has no beats", code="empty_script")
    if beats[0]["type"] != "headline":
        beats[0]["type"] = "headline"
    data["beats"] = beats
    return data


def stage_news_script(ctx: ProjectContext, opts: dict) -> str:
    out = ctx.work / "script.json"
    force = bool(opts.get("force"))
    if out.exists() and not force:
        return "existing work/script.json"
    art = Article.load(ctx.dir / "source" / "article.json")
    p = ctx.project
    o = {**p.options}
    mode = o.get("rewrite", "auto")
    if mode == "none":
        data = _passthrough(art, o, p.language)
    elif mode == "llm":
        data = _llm_script(ctx, art, o, force)
    else:
        try:
            data = _llm_script(ctx, art, o, force)
        except ManualGateRequired:
            log.warning("[news_script] no AI CLI available - building beats from the article text "
                        "(options.rewrite=auto); a summary by AI is better than reading the article verbatim")
            data = _passthrough(art, o, p.language)
    data = _check_script(data, len(art.images))
    if not data["beats"][0]["headline"]:
        data["beats"][0]["headline"] = art.title
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    words = sum(len(b["narration"].split()) for b in data["beats"])
    kinds = ", ".join(f"{k}={sum(b['type'] == k for b in data['beats'])}" for k in BEAT_TYPES
                      if any(b["type"] == k for b in data["beats"]))
    return f"{data.get('source')}: {len(data['beats'])} beats ({kinds}), ~{words / WORDS_PER_SEC[p.language]:.0f}s"


# ------------------------------------------------------------------ stage: news_media


RESIZE_PARAMS = {"w", "h", "width", "height", "crop", "scale", "resize", "fit", "q", "quality", "mode"}


def _full_size(url: str) -> str:
    """The CDN URL without resize parameters (?w=660&h=420...) - news sites serve the original then."""
    u = httpx.URL(url)
    kept = [(k, v) for k, v in u.params.multi_items() if k.lower() not in RESIZE_PARAMS]
    return str(u.copy_with(params=kept)) if len(kept) != len(u.params.multi_items()) else url


def _download(url: str, dest_stem: Path, client: httpx.Client) -> Path:
    full = _full_size(url)
    for candidate in dict.fromkeys([full, url]):
        try:
            return _fetch_image(candidate, dest_stem, client)
        except (httpx.HTTPError, OSError, ValueError):
            if candidate == url:
                raise
    raise AssertionError("unreachable")


def _fetch_image(url: str, dest_stem: Path, client: httpx.Client) -> Path:
    r = client.get(url)
    r.raise_for_status()
    if not r.headers.get("content-type", "image/").startswith("image/") or len(r.content) > MAX_IMAGE_BYTES:
        raise ValueError(f"not an image or too large ({r.headers.get('content-type')}, {len(r.content)} bytes)")
    ext = {"image/png": ".png", "image/webp": ".webp"}.get(r.headers.get("content-type", "").split(";")[0], ".jpg")
    dest = dest_stem.with_suffix(ext)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(r.content)
    with Image.open(tmp) as im:
        im.verify()
    tmp.replace(dest)
    return dest


def stage_news_media(ctx: ProjectContext, opts: dict) -> str:
    """work/news/media.json: one entry per article image (path null when unusable) + your files in images/."""
    out = ctx.work / "news" / "media.json"
    if out.exists() and not opts.get("force"):
        return "existing work/news/media.json"
    art = Article.load(ctx.dir / "source" / "article.json")
    p = ctx.project
    folder = ctx.work / "news"
    folder.mkdir(parents=True, exist_ok=True)
    entries, failed = [], []
    use_article = p.options.get("images", "article") == "article"
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30) as client:
        for i, im in enumerate(art.images):
            path = None
            if use_article:
                local = ctx.dir / im.src if not re.match(r"https?://", im.src) else None
                try:
                    if local is not None:
                        path = local if local.is_file() else None
                    else:
                        hit = sorted(folder.glob(f"img_{i:02d}.*"))
                        path = hit[0] if hit else _download(im.src, folder / f"img_{i:02d}", client)
                except (httpx.HTTPError, OSError, ValueError) as e:
                    failed.append(f"[{i}] {type(e).__name__}")
            entries.append({"path": path.relative_to(ctx.dir).as_posix() if path else None, "src": im.src,
                            "caption": im.caption, "credit": im.credit})
    named = {e["path"] for e in entries if e["path"]}
    own = sorted(f for f in (ctx.dir / "images").glob("*")
                 if f.suffix.lower() in IMAGE_EXT and f.relative_to(ctx.dir).as_posix() not in named)
    entries += [{"path": f.relative_to(ctx.dir).as_posix(), "src": f.name, "caption": "", "credit": "own"}
                for f in own]
    out.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in failed:
        log.warning("[news_media] image %s not usable - its beats use another photo", f)
    ok = sum(1 for e in entries if e["path"])
    return f"{ok}/{len(entries)} images usable" + (f" ({len(own)} from images/)" if own else "")


# ------------------------------------------------------------------ stage: news_scenes


KEN_BURNS = ("zoom_out", "pan_left", "zoom_in", "pan_right")


def stage_news_scenes(ctx: ProjectContext, opts: dict) -> str:
    p = ctx.project
    if p.scenes and not opts.get("force"):
        return f"kept {len(p.scenes)} existing scenes (use --force to rebuild)"
    art = Article.load(ctx.dir / "source" / "article.json")
    script = json.loads((ctx.work / "script.json").read_text(encoding="utf-8"))
    media = json.loads((ctx.work / "news" / "media.json").read_text(encoding="utf-8"))
    usable = [i for i, m in enumerate(media) if m["path"]]
    fmt, o = ctx.fmt, p.options
    w, h = fmt.width, fmt.height
    frames = ctx.work / "news" / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    common = {"width": w, "height": h, "fonts_dir": ctx.asset_dir("shared/fonts"), "safe": fmt.safe_zone,
              "brand": str(o.get("brand") or ""), "accent": str(o.get("accent") or "#FF5A1F")}
    lang = p.language
    clean = (lambda t: clean_for_speech(t, lang)) if o.get("speech_cleanup", True) else (lambda t: t.strip())
    scenes, credits, used = [], {}, []
    for n, beat in enumerate(script["beats"], start=1):
        kind = beat["type"]
        idx = beat["image"] if beat["image"] in usable else None
        if idx is None and usable and kind != "stat":  # no (usable) image named: the least-used photo
            idx = min(usable, key=lambda i: (used.count(i), i))
        if idx is None and kind in ("photo", "quote", "card"):
            kind = "stat" if beat["value"] else "photo"
        sid = f"n{n:02d}_{kind}"
        m = media[idx] if idx is not None else None
        src = ctx.dir / m["path"] if m else None
        still = frames / f"{sid}.jpg"
        if kind == "quote":  # alternate the tilt so two quotes of the same person do not look identical
            still_framed(src, still, w, h, tilt=-3.0 if sum(s.scene_id.endswith("_quote") for s in scenes) % 2 == 0
                         else 3.0)
        elif kind == "card":
            still_card(src, still, w, h)
        elif kind == "stat" or src is None:
            still_backdrop(src, still, w, h)
        else:
            still_photo(src, still, w, h)
        who = (m["credit"] if m and m["credit"] and m["credit"] != "own" else art.publisher) or ""
        chip = CHIP[lang].format(who=who) if m and who else (art.publisher or "")
        if kind == "headline" and art.date_label:
            chip = f"{chip} · {art.date_label}" if chip else art.date_label
        overlay = news_overlay(frames / f"{sid}_text.png", kind=kind, chip=chip,
                               headline=beat["headline"] or art.title, category=beat["category"] or art.section or "",
                               name=beat["name"], role=beat["role"], value=beat["value"], label=beat["label"],
                               note=beat["note"], title_chip=art.title if kind == "stat" else "", **common)
        effect = "zoom_in" if kind in ("headline", "quote", "card", "stat") else KEN_BURNS[n % len(KEN_BURNS)]
        scenes.append(Scene(scene_id=sid, narration=clean(beat["narration"]),
                            visual=VisualSpec(type="still", path=still.relative_to(ctx.dir).as_posix(),
                                              fit_mode="crop", ken_burns=effect,
                                              overlay=overlay.relative_to(ctx.dir).as_posix()),
                            source_note=(f"{m['caption']} ({who})" if m and m["caption"] else (who or None))))
        if idx is not None:
            used.append(idx)
            if m["credit"] != "own" and idx not in credits:
                credits[idx] = {"scene_id": sid, "title": m["caption"] or art.title, "author": who,
                                "license": f"© {art.publisher or who} - used with credit", "page": art.url or ""}
    p.scenes = scenes
    p.title = p.title or script.get("title") or art.title
    desc = script.get("description") or art.lead[:280]
    p.description = p.description or f"{desc}\n\n{art.credit()}".strip()
    if not p.hashtags:
        p.hashtags = [t if t.startswith("#") else f"#{t}" for t in script.get("hashtags", []) if t]
    p.options["image_credits"] = list(credits.values())
    ctx.save()
    return f"{len(scenes)} scenes, {len(set(used))} photos"


STAGES = {"article": stage_article, "news_script": stage_news_script, "news_media": stage_news_media,
          "news_scenes": stage_news_scenes}
