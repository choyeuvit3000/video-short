"""N1 newspaper: a news article (URL, saved page or pasted text) -> a short news video.

Stages: article -> news_script -> news_media -> news_scenes -> (validate, voice, render, qc, package)
  article     : source/article.json from source/article.html (page saved from the browser), source/source.md
                (pasted markdown, or a saved page given with --text-file) or project.source.url (one request)
  news_script : work/script.json - one beat per idea of the voice-over, with a role (hook | quote | fact | number |
                document | timeline | closing), written by an AI CLI or built from the article text when no CLI
                answers (options.rewrite=auto)
  news_media  : the article's photos downloaded to work/news/ (+ your files in images/ + freely licensed
                illustrations from Wikimedia Commons for the beats' `image_query`), credited
  news_scenes : news_planner picks a layout per role from assets/shared/layouts/news.yaml, checks the on-screen
                facts against the article, and renderers/news draws a still + a text overlay per scene
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
from ..renderers.news import Frame, render_layout
from ..renderers.render import caption_band_top, caption_style
from . import fill, load_workflow, read_prompt
from .news_planner import ROLES, load_layout_config, normalize_beat, person_caption, plan_scenes
from .story_reader import WORDS_PER_SEC, story_sentences

log = get_logger()

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
MAX_IMAGE_BYTES = 15 * 1024 * 1024
LANG_NAME = {"vi": "Vietnamese (tiếng Việt, natural spoken news style)", "en": "English (natural spoken news style)"}

_S = {"type": "string"}
SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "upload title, max 90 characters"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": list(ROLES)},
                    "narration": {"type": "string", "description": "spoken text, 1-2 short sentences"},
                    "image": {"type": "integer", "description": "index into the image list, -1 for none"},
                    "image_query": {"type": "string", "description": "English Wikimedia Commons query, or ''"},
                    "headline": {"type": "string", "description": "hook: max 60 chars; document/timeline: title"},
                    "highlight": {"type": "string", "description": "hook/closing: words of the headline to colour"},
                    "category": {"type": "string", "description": "hook: 1-2 words"},
                    "kicker": {"type": "string", "description": "small label above a card, 1-3 words"},
                    "name": {"type": "string", "description": "quote: who speaks, as written in the article"},
                    "title": {"type": "string", "description": "quote: their position"},
                    "value": {"type": "string", "description": "number: the number, max 8 characters"},
                    "unit": {"type": "string", "description": "number: what it counts, 1-3 words"},
                    "explain": {"type": "string", "description": "number: one line on what the number means"},
                    "points": {"type": "array", "items": _S, "description": "document: 2-4 short key points"},
                    "dates": {"type": "array", "description": "timeline: 2-4 milestones",
                              "items": {"type": "object", "properties": {"date": _S, "text": _S},
                                        "required": ["date", "text"]}},
                },
                "required": ["role", "narration", "image", "image_query", "headline", "highlight", "category",
                             "kicker", "name", "title", "value", "unit", "explain", "points", "dates"],
            },
        },
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "beats", "description", "hashtags"],
}


def _empty_beat(role: str, narration: str, image: int = -1, **kw) -> dict:
    beat = {"role": role, "narration": narration, "image": image, "image_query": "", "headline": "",
            "highlight": "", "category": "", "kicker": "", "name": "", "title": "", "value": "", "unit": "",
            "explain": "", "points": [], "dates": []}
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


_BIG_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+|\d{3,}|\d+(?:,\d+)?\s?%)(?![\w.,]\d)")


def _passthrough(art: Article, opts: dict, lang: str) -> dict:
    """Beats straight from the complete article text: hook (title + lead), then 1-2 sentence beats. A
    quoted sentence of a pictured person becomes a quote, a sentence with a big number a number card."""
    n_img = len(art.images)
    people = [(i, *person_caption(im.caption)) for i, im in enumerate(art.images) if person_caption(im.caption)[0]]
    beats = [_empty_beat("hook", art.lead or art.title, 0 if n_img else -1, headline=art.title,
                         category=art.section or "")]
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
    numbers = 0
    for text in chunks:
        quoted = next(((i, name, title) for i, name, title in people
                       if re.search(r"[\"“”]", text) and name.split()[-1] in text), None)
        big = _BIG_NUMBER.search(text)
        if quoted:
            beats.append(_empty_beat("quote", text, quoted[0], name=quoted[1], title=quoted[2]))
        elif big and numbers < 2:
            unit = " ".join(re.split(r"[,.;:!?]", text[big.end():].strip())[0].split()[:2])
            beats.append(_empty_beat("number", text, -1, value=big.group(1).replace(" ", ""), unit=unit))
            numbers += 1
        else:
            beats.append(_empty_beat("fact", text, -1))
    return {"title": art.title, "beats": beats, "description": art.lead[:280], "hashtags": [], "source": "passthrough"}


def _llm_script(ctx: ProjectContext, art: Article, opts: dict, force: bool) -> dict:
    p = ctx.project
    target = opts.get("target_sec")
    images = "\n".join(f"[{i}] {im.caption or '(no caption)'}" for i, im in enumerate(art.images)) or "(none)"
    prompt = fill(read_prompt(ctx.settings, "newspaper", "script.md"), {
        "language": LANG_NAME[p.language],
        "length_guidance": (f"Optional pacing reference: {target} seconds. Preserve all essential content even if "
                            "the video runs longer; never speed up speech to fit it." if target else
                            "No duration or word limit. Let complete content and a natural reading pace "
                            "set the length."),
        "beats": opts.get("beats") or "as many as the story needs",
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
        beat = normalize_beat(b)
        if not beat["narration"]:
            continue
        if not 0 <= beat["image"] < n_images:
            beat["image"] = -1
        beats.append(beat)
    if not beats:
        raise ValidationError("script has no beats", code="empty_script")
    if beats[0]["role"] != "hook":
        beats[0]["role"] = "hook"
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
    kinds = ", ".join(f"{k}={sum(b['role'] == k for b in data['beats'])}" for k in ROLES
                      if any(b["role"] == k for b in data["beats"]))
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
    extra = _commons_extras(ctx, folder) if p.options.get("extra_images", "commons") == "commons" else []
    entries += extra
    if out.exists():  # keep what you set by hand after looking at the photos (kind, focus)
        old = {e.get("path"): e for e in json.loads(out.read_text(encoding="utf-8")) if e.get("path")}
        for e in entries:
            e.update({k: old[e["path"]][k] for k in ("kind", "focus", "verified")
                      if e["path"] in old and k in old[e["path"]]})
    out.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in failed:
        log.warning("[news_media] image %s not usable - its beats use another photo", f)
    ok = sum(1 for e in entries if e["path"])
    return (f"{ok}/{len(entries)} images usable" + (f" ({len(own)} from images/)" if own else "")
            + (f" ({len(extra)} illustrations from Wikimedia Commons)" if extra else ""))


def _commons_extras(ctx: ProjectContext, folder: Path) -> list[dict]:
    """More photos when the article has few: the script's `image_query` per beat (and options.image_queries),
    freely licensed files from Wikimedia Commons (official API), credited and marked as illustrations - they
    show the place or thing named, never the event itself, so they are only used for context scenes."""
    from ..providers.images import find_photo

    script_file = ctx.work / "script.json"
    beats = json.loads(script_file.read_text(encoding="utf-8")).get("beats", []) if script_file.exists() else []
    queries = [(n, str(b.get("image_query") or "").strip()) for n, b in enumerate(beats)]
    queries = [(n, q) for n, q in queries if q]
    queries += [(None, str(q).strip()) for q in ctx.project.options.get("image_queries") or [] if str(q).strip()]
    limit = int(ctx.project.options.get("max_extra_images", 3))
    out, used = [], set()
    for n, q in queries[:limit]:
        try:
            hit = find_photo(ctx.settings.path("cache"), q, folder / f"commons_{len(out):02d}", avoid=used)
        except ProviderUnavailable as e:
            log.warning("[news_media] Wikimedia Commons '%s': %s", q, e)
            continue
        if hit is None:
            log.warning("[news_media] no free photo on Wikimedia Commons for '%s'", q)
            continue
        path, photo = hit
        used.add(photo.title)
        out.append({"path": path.relative_to(ctx.dir).as_posix(), "src": photo.url, "page": photo.page,
                    "caption": photo.title.removeprefix("File:").rsplit(".", 1)[0], "credit": photo.credit(),
                    "author": photo.author, "license": photo.license, "license_url": photo.license_url,
                    "origin": "commons", "kind": "editorial", "query": q, "for_beat": n})
    return out


# ------------------------------------------------------------------ stage: news_scenes


def stage_news_scenes(ctx: ProjectContext, opts: dict) -> str:
    """Plan each beat (news_planner: layout by role, asset, verified text, fallback), draw it (renderers/news),
    and write project.json scenes + work/news/scene_plan.json (output/scene_plan.json adds start/end times)."""
    p = ctx.project
    if p.scenes and not opts.get("force"):
        return f"kept {len(p.scenes)} existing scenes (use --force to rebuild)"
    art = Article.load(ctx.dir / "source" / "article.json")
    script = json.loads((ctx.work / "script.json").read_text(encoding="utf-8"))
    media = json.loads((ctx.work / "news" / "media.json").read_text(encoding="utf-8"))
    cfg = load_layout_config(ctx)
    beats = [normalize_beat(b) for b in script["beats"]]
    lang = p.language
    plans = plan_scenes(beats, media, art, cfg, lang=lang)
    fmt, o = ctx.fmt, p.options
    cap_cfg = cfg.get("caption") or {}
    if cap_cfg.get("style") and p.video.caption_style != cap_cfg["style"] and not o.get("keep_caption_style"):
        p.video.caption_style = str(cap_cfg["style"])
    style = caption_style(ctx)
    limit_y = caption_band_top(fmt, style) - int(cap_cfg.get("gap", 40) * min(fmt.width, fmt.height) / 1080)
    motion = cfg.get("motion") or {}
    frames = ctx.work / "news" / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    clean = (lambda t: clean_for_speech(t, lang)) if o.get("speech_cleanup", True) else (lambda t: t.strip())
    brand = str(o.get("brand") or "")
    scenes, credits = [], {}
    for n, plan in enumerate(plans, start=1):
        sid = f"n{n:02d}_{plan['layout']}"
        plan["scene_id"] = sid
        a = plan["asset"]
        src = ctx.dir / a["path"] if a else None
        params = (cfg.get("layouts") or {}).get("document" if plan["layout"] == "text_card" else plan["layout"]) or {}
        fr = Frame(width=fmt.width, height=fmt.height, fonts_dir=ctx.asset_dir("shared/fonts"),
                   safe={**fmt.safe_zone, **style.get("safe_zone", {})},
                   limit_y=limit_y, theme=cfg.get("theme") or {}, params=params)
        chip = plan["chip"]
        if plan["layout"] == "headline" and art.date_label:
            chip = f"{chip} · {art.date_label}" if chip else art.date_label
        still, overlay = render_layout(plan, frames / f"{sid}.jpg", frames / f"{sid}_text.png", fr, src, chip=chip,
                                       brand=brand)
        appear = float(motion.get("appear_sec", 0.35)) if plan["layout"] == "stat_card" else 0
        scenes.append(Scene(
            scene_id=sid, narration=clean(plan["narration"]), duration_sec=plan.get("min_hold_sec"),
            visual=VisualSpec(type="still", path=still.relative_to(ctx.dir).as_posix(), fit_mode="crop",
                              ken_burns=plan["ken_burns"],
                              ken_burns_amount=float(motion.get("ken_burns_amount", 0.045)),
                              overlay=overlay.relative_to(ctx.dir).as_posix(),
                              overlay_in=appear or None, overlay_rise_px=int(motion.get("rise_px", 36)) or None),
            source_note=(f"{a['caption']} ({a['credit']})" if a and a.get("caption") else None),
            plan={k: plan[k] for k in ("role", "layout", "text", "asset", "fallback", "notes", "focus")}))
        if a and a.get("credit") != "own" and a["index"] not in credits and plan["layout"] != "stat_card":
            m = media[a["index"]]
            commons = m.get("origin") == "commons"
            credits[a["index"]] = {
                "scene_id": sid, "title": m.get("caption") or art.title,
                "author": m.get("author") if commons else (m.get("credit") or art.publisher or ""),
                "license": m.get("license") if commons else f"© {art.publisher or m.get('credit')} - used with credit",
                "license_url": m.get("license_url", "") if commons else "",
                "page": m.get("page") if commons else (art.url or "")}
    p.scenes = scenes
    p.title = p.title or script.get("title") or art.title
    desc = script.get("description") or art.lead[:280]
    p.description = p.description or f"{desc}\n\n{art.credit()}".strip()
    if not p.hashtags:
        p.hashtags = [t if t.startswith("#") else f"#{t}" for t in script.get("hashtags", []) if t]
    p.options["image_credits"] = list(credits.values())
    ctx.save()
    (ctx.work / "news" / "scene_plan.json").write_text(json.dumps(plans, ensure_ascii=False, indent=1),
                                                       encoding="utf-8")
    fell = [pl["scene_id"] for pl in plans if pl["fallback"] or pl["notes"]]
    for pl in plans:
        for why in ([pl["fallback"]] if pl["fallback"] else []) + pl["notes"]:
            log.warning("[news_scenes] %s: %s", pl["scene_id"], why)
    layouts = ", ".join(pl["layout"] for pl in plans)
    return f"{len(scenes)} scenes ({layouts})" + (f", {len(fell)} with a fallback" if fell else "")


STAGES = {"article": stage_article, "news_script": stage_news_script, "news_media": stage_news_media,
          "news_scenes": stage_news_scenes}
