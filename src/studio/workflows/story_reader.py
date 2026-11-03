"""S1 story_reader: a Reddit/Threads/web post read aloud over a background, post card on the first scene.

Stages: source -> script -> scenes -> (validate, voice, render, qc, package)
  source  : source/source.json from source/source.md (pasted), project.source.url, or the Reddit API
  script  : work/script.json - LLM rewrite/translate (claude/agy/codex CLI) or passthrough of the text
  scenes  : project.json scenes + work/card.png (only when the project has no scenes yet)
"""

from __future__ import annotations

import hashlib
import json
import re

from ..core.errors import ManualGateRequired, ValidationError
from ..core.logging_utils import get_logger
from ..core.project import ProjectContext
from ..core.schema import Scene, VisualSpec
from ..providers.llm import generate_json
from ..providers.source import SourcePost, from_text_file, from_url
from ..renderers.card import render_post_card
from . import fill, load_workflow, read_prompt

log = get_logger()

LANG_NAME = {"vi": "Vietnamese (tiếng Việt, natural spoken style)", "en": "English (natural spoken US style)"}
WORDS_PER_SEC = {"vi": 3.2, "en": 2.6}
DEFAULT_CTA = {
    "vi": "Bạn nghĩ sao về câu chuyện này? Bình luận cho mình biết nhé.",
    "en": "What would you have done? Tell me in the comments.",
}
COMMENT_PREFIX = {"vi": "Một bình luận nổi bật: ", "en": "One top comment said: "}
VI_CHARS = set("ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ")
MEDIA_EXT = (".mp4", ".mov", ".mkv", ".webm", ".png", ".jpg", ".jpeg", ".webp")

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "short title shown on the card, in the target language"},
        "hook": {"type": "string", "description": "first spoken line, read over the post card"},
        "segments": {"type": "array", "items": {"type": "string"},
                     "description": "narration in order, 1-3 sentences each"},
        "cta": {"type": "string"},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "hook", "segments", "cta", "description", "hashtags"],
}


def guess_lang(text: str) -> str:
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return "en"
    vi = sum(1 for c in letters if c in VI_CHARS)
    return "vi" if vi / len(letters) > 0.01 else "en"


def split_sentences(text: str, max_chars: int) -> list[str]:
    """Paragraphs -> chunks of whole sentences no longer than max_chars (a single long sentence stays whole)."""
    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = " ".join(para.split())
        if not para:
            continue
        sentences = re.split(r"(?<=[.!?…])\s+", para)
        cur = ""
        for s in sentences:
            if cur and len(cur) + 1 + len(s) > max_chars:
                chunks.append(cur)
                cur = s
            else:
                cur = f"{cur} {s}".strip()
        if cur:
            chunks.append(cur)
    return chunks


# ------------------------------------------------------------------ stage: source


def stage_source(ctx: ProjectContext, opts: dict) -> str:
    src_json = ctx.dir / "source" / "source.json"
    if src_json.exists() and not opts.get("force"):
        post = SourcePost.load(src_json)
        return f"existing source.json ({post.platform})"
    md = ctx.dir / "source" / "source.md"
    p = ctx.project
    if md.exists():
        post = from_text_file(md)
        stype = "manual"
    elif p.source.url:
        post = from_url(p.source.url, max_comments=int(p.options.get("include_comments", 0)) or 5)
        stype = "reddit" if post.platform == "reddit" else "url"
    else:
        raise ManualGateRequired("source", (
            "### Source text\n\n"
            "Paste the post into `source/source.md`:\n\n"
            "```\n# Post title\nurl: https://... (optional)\nauthor: name (optional)\n"
            "community: AskReddit (optional)\n\n"
            "Post body...\n```\n\n"
            "Or set `source.url` in project.json (Reddit needs REDDIT_CLIENT_ID/SECRET in .env).\n"
        ))
    if post.nsfw and not p.options.get("allow_nsfw"):
        raise ValidationError("source post is marked NSFW - set options.allow_nsfw=true to use it", code="nsfw")
    post.language = post.language or guess_lang(f"{post.title}\n{post.body}")
    post.save(src_json)
    p.source.type = stype if p.source.type == "none" else p.source.type
    p.source.platform = post.platform
    p.source.url = post.url or p.source.url
    p.source.author, p.source.community = post.author, post.community
    p.source.title, p.source.score, p.source.fetched_at = post.title, post.score, post.fetched_at
    p.source.credit_text = p.source.credit_text or post.credit()
    ctx.save()
    return f"{post.platform}: {len(post.body)} chars, lang={post.language}"


# ------------------------------------------------------------------ stage: script


def _passthrough(post: SourcePost, lang: str, opts: dict) -> dict:
    max_chars = int(opts.get("scene_max_chars", 260))
    segments = split_sentences(post.body, max_chars)
    n_comments = int(opts.get("include_comments", 0))
    for c in post.comments[:n_comments]:
        body = " ".join(c.get("body", "").split())
        if body:
            segments += split_sentences(COMMENT_PREFIX[lang] + body, max_chars)
    return {
        "title": post.title,
        "hook": post.title,
        "segments": segments,
        "cta": opts.get("cta", DEFAULT_CTA[lang]),
        "description": post.title,
        "hashtags": [],
    }


def _llm_script(ctx: ProjectContext, post: SourcePost, opts: dict, force: bool) -> dict:
    p = ctx.project
    target = int(opts.get("target_sec", 60))
    comments = "\n".join(f"- ({c.get('score')}) {c.get('author')}: {' '.join(c.get('body', '').split())}"
                         for c in post.comments[: int(opts.get("include_comments", 0))]) or "(none)"
    prompt = fill(read_prompt(ctx.settings, "story_reader", "script.md"), {
        "language": LANG_NAME[p.language],
        "target_sec": target,
        "max_words": int(target * WORDS_PER_SEC[p.language]),
        "platform": post.platform,
        "community": post.community or "-",
        "title": post.title,
        "body": post.body.strip() or "(title only)",
        "comments": comments,
        "cta_hint": opts.get("cta", DEFAULT_CTA[p.language]),
    })
    wf = load_workflow(ctx.settings, "story_reader")
    data, provider = generate_json(ctx, "script", prompt, SCRIPT_SCHEMA, chain=wf.get("llm_chain"), force=force)
    data["_provider"] = provider
    return data


def stage_script(ctx: ProjectContext, opts: dict) -> str:
    out = ctx.work / "script.json"
    force = bool(opts.get("force"))
    if out.exists() and not force:
        return "existing work/script.json"
    post = SourcePost.load(ctx.dir / "source" / "source.json")
    p = ctx.project
    o = {**p.options}
    mode = o.get("rewrite", "auto")
    src_lang = post.language or guess_lang(post.body)
    needs_translation = src_lang != p.language
    if mode == "none":
        if needs_translation:
            raise ValidationError(f"source is '{src_lang}' but project language is '{p.language}' - "
                                  "set options.rewrite to 'llm' (translation needs an AI)", code="needs_llm")
        data, how = _passthrough(post, p.language, o), "passthrough"
    elif mode == "llm" or needs_translation:
        data = _llm_script(ctx, post, o, force)
        how = data.pop("_provider")
    else:  # auto: use an AI CLI if one answers, else read the text as-is
        try:
            data = _llm_script(ctx, post, o, force)
            how = data.pop("_provider")
        except ManualGateRequired:
            log.warning("[script] no AI CLI available - reading the post as-is (options.rewrite=auto)")
            data, how = _passthrough(post, p.language, o), "passthrough"
    data["segments"] = [s.strip() for s in data.get("segments", []) if s and s.strip()]
    if not data["segments"] and not data.get("hook"):
        raise ValidationError("script is empty", code="empty_script")
    data["source"] = how
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    words = sum(len(t.split()) for t in [data.get("hook", ""), *data["segments"], data.get("cta", "")])
    est = words / WORDS_PER_SEC[p.language]
    if est > ctx.fmt.max_duration_sec:
        log.warning("[script] ~%.0fs of narration > %ss limit of %s - shorten work/script.json", est,
                    ctx.fmt.max_duration_sec, ctx.fmt.name)
    return f"{how}: {len(data['segments'])} segments, ~{est:.0f}s"


# ------------------------------------------------------------------ stage: scenes


def _pick_background(ctx: ProjectContext) -> str:
    folder = ctx.settings.path("assets") / "workflows" / "story_reader" / "backgrounds"
    files = sorted(f for f in folder.glob("*") if f.suffix.lower() in MEDIA_EXT) if folder.is_dir() else []
    if not files:
        return "gradient"
    idx = int(hashlib.sha1(ctx.project.project_id.encode()).hexdigest(), 16) % len(files)
    return "asset:" + files[idx].relative_to(ctx.settings.path("assets")).as_posix()


def stage_scenes(ctx: ProjectContext, opts: dict) -> str:
    p = ctx.project
    if p.video.background == "auto":
        p.video.background = _pick_background(ctx)
    if p.scenes and not opts.get("force"):
        ctx.save()
        return f"kept {len(p.scenes)} existing scenes (use --force to rebuild)"
    script = json.loads((ctx.work / "script.json").read_text(encoding="utf-8"))
    post = SourcePost.load(ctx.dir / "source" / "source.json")
    o = p.options
    fmt = ctx.fmt
    card_title = script.get("title") or post.title
    card = render_post_card(
        ctx.work / "card.png", video_width=fmt.width,
        title=card_title, community=post.community, author=post.author, score=post.score,
        platform=post.platform if post.platform in ("reddit", "threads") else "web",
        theme=o.get("card_theme", "light"), fonts_dir=ctx.asset_dir("shared/fonts"),
        width_ratio=float(o.get("card_width_ratio", 0.86)),
    )
    max_chars = int(o.get("scene_max_chars", 260))
    texts = []
    for seg in script["segments"]:
        texts += split_sentences(seg, max_chars) if len(seg) > max_chars else [seg]
    scenes = [Scene(scene_id="s01_hook", narration=script.get("hook") or card_title,
                    visual=VisualSpec(type="background", overlay=card.relative_to(ctx.dir).as_posix()))]
    for i, t in enumerate(texts, start=2):
        scenes.append(Scene(scene_id=f"s{i:02d}", narration=t, visual=VisualSpec(type="background")))
    if script.get("cta"):
        scenes.append(Scene(scene_id=f"s{len(scenes) + 1:02d}_cta", narration=script["cta"],
                            visual=VisualSpec(type="background")))
    p.scenes = scenes
    p.title = p.title or card_title
    p.description = p.description or script.get("description", "")
    if not p.hashtags:
        p.hashtags = [h if h.startswith("#") else f"#{h}" for h in script.get("hashtags", []) if h]
    ctx.save()
    return f"{len(scenes)} scenes, background={p.video.background}"


STAGES = {"source": stage_source, "script": stage_script, "scenes": stage_scenes}
