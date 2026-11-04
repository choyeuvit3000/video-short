"""S1 story_reader: a Reddit/Threads/web post read aloud over a background, post card on the first scene.

Stages: source -> script -> scenes -> (validate, voice, render, qc, package)
  source  : source/source.json from source/source.md (pasted), project.source.url, or the Reddit API
  script  : work/script.json - LLM rewrite/translate (claude/agy/codex CLI) or passthrough of the text
  scenes  : project.json scenes + work/card.png (only when the project has no scenes yet)
            options.layout = post (post card, then the background with word captions) | passage (audio-story
            look: one scene per sentence over a passage card that highlights it, hook / title / end cards)
            options.part_max_sec > 0 splits a long story into balanced parts: this project is part 1 and
            sibling projects <dir>_p2, <dir>_p3... are created next to it, ready for `studio run`
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path

from ..core.errors import ManualGateRequired, ValidationError
from ..core.logging_utils import get_logger
from ..core.project import ProjectContext, scaffold
from ..core.schema import Project, Scene, VisualSpec
from ..core.textnorm import clean_for_speech
from ..providers.llm import generate_json
from ..providers.source import SourcePost, from_text_file, from_url
from ..renderers.card import render_end_card, render_hook_card, render_passage_card, render_post_card
from . import fill, load_workflow, read_prompt

log = get_logger()

LANG_NAME = {"vi": "Vietnamese (tiếng Việt, natural spoken style)", "en": "English (natural spoken US style)"}
WORDS_PER_SEC = {"vi": 3.2, "en": 2.6}
DEFAULT_CTA = {
    "vi": "Bạn nghĩ sao về câu chuyện này? Bình luận cho mình biết nhé.",
    "en": "What would you have done? Tell me in the comments.",
}
COMMENT_PREFIX = {"vi": "Một bình luận nổi bật: ", "en": "One top comment said: "}
PART_BADGE = {"vi": "Phần {k}/{n}", "en": "Part {k}/{n}"}
PART_INTRO = {"vi": "Phần {k}.", "en": "Part {k}."}
CONTINUES = {"vi": "Còn tiếp ở phần {k}.", "en": "To be continued in part {k}."}
THE_END = {"vi": "Hết truyện.", "en": "The end."}
# a sentence ends at . ! ? … (plus closing quotes) followed by what looks like the start of the next one
STORY_SENT_RE = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][\"”’»)]))\s+(?=[\"“‘«(]?[A-ZÀ-Ỹ0-9Đ\"“‘«(-])")
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


def story_sentences(text: str) -> list[str]:
    """Sentences of one paragraph; tiny fragments ("Không." "Nó.") are glued to a neighbour."""
    parts = [s.strip() for s in STORY_SENT_RE.split(" ".join(text.split())) if s and s.strip()]
    merged: list[str] = []
    for s in parts:
        if merged and (len(s) < 14 or len(merged[-1]) < 14) and len(merged[-1]) + len(s) < 200:
            merged[-1] += " " + s
        else:
            merged.append(s)
    return merged


def passages(segments: list[str], max_chars: int = 240, max_sentences: int = 3) -> list[list[str]]:
    """Group the sentences of each segment into card-sized passages (a passage never spans two segments)."""
    out: list[list[str]] = []
    for seg in segments:
        cur: list[str] = []
        for s in story_sentences(seg):
            if cur and (sum(len(x) for x in cur) + len(s) > max_chars or len(cur) >= max_sentences):
                out.append(cur)
                cur = []
            cur.append(s)
        if cur:
            out.append(cur)
    return out


def split_parts(durations: list[float], budget: float) -> list[list[int]]:
    """Indexes of `durations` cut into as few parts as `budget` allows, each part close to an equal share
    (no short tail part). An item longer than the budget gets a part of its own."""
    total = sum(durations)
    if budget <= 0 or total <= budget or len(durations) < 2:
        return [list(range(len(durations)))]
    n_target = math.ceil(total / budget)
    while True:
        parts: list[list[int]] = []
        cur: list[int] = []
        cur_t = done_t = 0.0
        for i, t in enumerate(durations):
            share = (total - done_t) / max(1, n_target - len(parts))  # what each remaining part gets
            over = cur_t + t > budget
            past = bool(cur) and len(parts) < n_target - 1 and abs(cur_t + t - share) > abs(cur_t - share)
            if cur and (over or past):
                parts.append(cur)
                done_t += cur_t
                cur, cur_t = [], 0.0
            cur.append(i)
            cur_t += t
        if cur:
            parts.append(cur)
        if len(parts) <= n_target:
            return parts
        n_target += 1  # a long item forced an extra cut: re-balance with one more part


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
        post = from_url(p.source.url, max_comments=int(p.options.get("include_comments", 0)) or 5,
                        cache_dir=ctx.settings.path("cache"))
        stype = post.platform if post.platform in ("reddit", "threads") else "url"
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
        shared = ctx.settings.path("assets") / "shared" / "backgrounds"
        files = sorted(p for p in shared.glob("*") if p.suffix.lower() in MEDIA_EXT)
    if not files:
        return "gradient"
    idx = int(hashlib.sha1(ctx.project.project_id.encode()).hexdigest(), 16) % len(files)
    return "asset:" + files[idx].relative_to(ctx.settings.path("assets")).as_posix()


def _story(ctx: ProjectContext, script: dict) -> dict:
    """Script texts as they will be read: cleaned for speech (options.speech_cleanup, default on)."""
    p = ctx.project
    lang = p.language
    clean = (lambda t: clean_for_speech(t, lang)) if p.options.get("speech_cleanup", True) else (lambda t: t.strip())
    post = SourcePost.load(ctx.dir / "source" / "source.json")
    title = clean(script.get("title") or post.title)
    hook = clean(script.get("hook") or "")
    segments = [c for c in (clean(s) for s in script["segments"]) if c]
    return {"post": post, "title": title, "hook": hook, "segments": segments,
            "cta": clean(script.get("cta") or ""), "description": script.get("description", ""),
            "hashtags": script.get("hashtags", [])}


def _units(story: dict, o: dict) -> list:
    """What a part is cut from: passages (list of sentences) or scene texts."""
    if o.get("layout", "post") == "passage":
        return passages(story["segments"], int(o.get("passage_max_chars", 240)))
    max_chars = int(o.get("scene_max_chars", 260))
    texts: list[str] = []
    for seg in story["segments"]:
        texts += split_sentences(seg, max_chars) if len(seg) > max_chars else [seg]
    return texts


def _est_sec(text: str, lang: str, speed: float) -> float:
    return len(text.split()) / WORDS_PER_SEC[lang] / speed + 0.25


def _plan_parts(ctx: ProjectContext, story: dict, units: list) -> list[list]:
    p = ctx.project
    max_sec = float(p.options.get("part_max_sec", 0) or 0)
    if max_sec <= 0:
        return [units]
    lang, speed = p.language, p.audio.speed
    durs = [_est_sec(" ".join(u) if isinstance(u, list) else u, lang, speed) for u in units]
    lead = story["hook"] if story["hook"] and story["hook"] != story["title"] else ""
    overhead = sum(_est_sec(t, lang, speed) for t in [lead, f"{story['title']} {PART_INTRO[lang]}",
                                                      story["cta"] or THE_END[lang]] if t)
    parts = split_parts(durs, max(max_sec - overhead, max_sec * 0.5))
    return [[units[i] for i in idx] for idx in parts]


def _build_scenes(ctx: ProjectContext, story: dict, units: list, k: int, n: int) -> list[Scene]:
    """Scenes (and their card PNGs in work/) for part k of n."""
    p, o, fmt = ctx.project, ctx.project.options, ctx.fmt
    lang = p.language
    post = story["post"]
    card_kw = {
        "community": post.community, "author": post.author,
        "platform": post.platform if post.platform in ("reddit", "threads") else "web",
        "theme": o.get("card_theme", "light"), "fonts_dir": ctx.asset_dir("shared/fonts"),
        "width_ratio": float(o.get("card_width_ratio", 0.86)),
    }
    badge = PART_BADGE[lang].format(k=k, n=n) if n > 1 else None
    card = render_post_card(ctx.work / "card.png", video_width=fmt.width, title=story["title"], score=post.score,
                            badge=badge, **card_kw)

    def rel(path) -> str:
        return path.relative_to(ctx.dir).as_posix()

    end_text = CONTINUES[lang].format(k=k + 1) if k < n else story["cta"]
    if o.get("layout", "post") != "passage":
        scenes = [Scene(scene_id="s01_hook", narration=story["hook"] or story["title"],
                        visual=VisualSpec(type="background", overlay=rel(card)))]
        for i, t in enumerate(units, start=2):
            scenes.append(Scene(scene_id=f"s{i:02d}", narration=t, visual=VisualSpec(type="background")))
        if end_text:
            tag = "_next" if k < n else "_cta"
            scenes.append(Scene(scene_id=f"s{len(scenes) + 1:02d}{tag}", narration=end_text,
                                visual=VisualSpec(type="background")))
        return scenes

    cards = ctx.work / "cards"
    if cards.is_dir():
        shutil.rmtree(cards)  # generated only - rebuilt from the script below
    scenes = []
    hook = story["hook"]
    if hook and hook != story["title"]:
        png = render_hook_card(cards / "hook.png", video_width=fmt.width, video_height=fmt.height,
                               sentences=story_sentences(hook) or [hook], fonts_dir=card_kw["fonts_dir"])
        scenes.append(Scene(scene_id="s000_hook", narration=hook, visual=VisualSpec(type="background",
                                                                                    overlay=rel(png))))
    title_line = f"{story['title'].rstrip('.!?…')}. {PART_INTRO[lang].format(k=k)}" if n > 1 else story["title"]
    scenes.append(Scene(scene_id="s001_title", narration=title_line,
                        visual=VisualSpec(type="background", overlay=rel(card))))
    i = 1
    for pi, sents in enumerate(units, start=1):
        for j, sentence in enumerate(sents):
            i += 1
            png = render_passage_card(cards / f"p{pi:03d}_{j}.png", video_width=fmt.width, video_height=fmt.height,
                                      sentences=sents, current=j, **card_kw)
            scenes.append(Scene(scene_id=f"s{i:03d}", narration=sentence,
                                visual=VisualSpec(type="background", overlay=rel(png))))
    end_text = end_text or THE_END[lang]
    png = render_end_card(cards / "end.png", video_width=fmt.width, text=end_text, theme=card_kw["theme"],
                          fonts_dir=card_kw["fonts_dir"], width_ratio=card_kw["width_ratio"])
    scenes.append(Scene(scene_id=f"s{i + 1:03d}_end", narration=end_text,
                        visual=VisualSpec(type="background", overlay=rel(png))))
    return scenes


def _fill_project(ctx: ProjectContext, story: dict, units: list, k: int, n: int) -> None:
    p = ctx.project
    p.scenes = _build_scenes(ctx, story, units, k, n)
    if n > 1:
        p.options.update(part=k, parts=n)
        p.title = p.title or f"{story['title']} ({PART_BADGE[p.language].format(k=k, n=n)})"
    p.title = p.title or story["title"]
    p.description = p.description or story["description"]
    if not p.hashtags:
        p.hashtags = [h if h.startswith("#") else f"#{h}" for h in story["hashtags"] if h]
    if p.options.get("layout") == "passage" and p.video.subtitle_mode == "burn_in" \
            and not p.options.get("passage_captions"):
        p.video.subtitle_mode = "sidecar"  # the passage card already shows the words; SRT is still written
    ctx.save()


def _write_sibling(ctx: ProjectContext, script_path: Path, story: dict, units: list, k: int, n: int,
                   force: bool) -> str:
    """Part k as its own project next to this one (source + script copied, scenes built)."""
    sib = ctx.dir.with_name(f"{ctx.dir.name}_p{k}")
    if (sib / "project.json").exists() and not force:
        return f"kept {sib.name}"
    p = ctx.project
    data = p.model_dump()
    data.update(project_id=f"{p.project_id[:59]}_p{k}", title="", scenes=[])
    data["options"] = {**p.options, "part": k, "parts": n, "part_of": ctx.dir.name}
    scaffold(sib, Project.model_validate(data), force=True)
    for f in ("source/source.json", "source/source.md"):
        if (ctx.dir / f).is_file():
            shutil.copy2(ctx.dir / f, sib / f)
    (sib / "work").mkdir(exist_ok=True)
    shutil.copy2(script_path, sib / "work" / "script.json")
    sctx = ProjectContext(sib, settings=ctx.settings)
    _fill_project(sctx, story, units, k, n)
    return f"created {sib.name}"


def stage_scenes(ctx: ProjectContext, opts: dict) -> str:
    p = ctx.project
    if p.video.background == "auto":
        p.video.background = _pick_background(ctx)
    if p.scenes and not opts.get("force"):
        ctx.save()
        return f"kept {len(p.scenes)} existing scenes (use --force to rebuild)"
    script_path = ctx.work / "script.json"
    story = _story(ctx, json.loads(script_path.read_text(encoding="utf-8")))
    parts = _plan_parts(ctx, story, _units(story, p.options))
    n = len(parts)
    if p.options.get("part_of"):  # a sibling made by part 1: build only its own part
        k = min(int(p.options.get("part", 1)), n)
        _fill_project(ctx, story, parts[k - 1], k, n)
        return f"part {k}/{n}: {len(p.scenes)} scenes, background={p.video.background}"
    _fill_project(ctx, story, parts[0], 1, n)
    made = [_write_sibling(ctx, script_path, story, parts[k - 1], k, n, bool(opts.get("force")))
            for k in range(2, n + 1)]
    for m in made:
        log.info("[scenes] %s", m)
    extra = f", {n} parts ({'; '.join(made)})" if n > 1 else ""
    return f"{len(p.scenes)} scenes, background={p.video.background}{extra}"


STAGES = {"source": stage_source, "script": stage_script, "scenes": stage_scenes}
