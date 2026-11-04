"""knowledge_explainer: science / history / finance / ... explainers drawn with Manim templates.

Stages: explainer -> review -> (validate, voice, render, qc, package)
  explainer : the LLM chain writes narration + one Manim template (with JSON params) per scene, plus the sources
              behind each claim, following the topic pack (workflows/_shared/topics/<topic>.yaml).
              Kept when scenes exist unless --force. Params are validated; a bad scene falls back to `title`.
  review    : manual gate - you check facts, sources and wording, then `studio approve <dir>`.
              Skipped when the topic has review_required: false or options.review is false.
No generated code runs: the model only picks a template and fills its params.
"""

from __future__ import annotations

import json
import re

from ..core.errors import ManualGateRequired, StudioError
from ..core.logging_utils import get_logger
from ..core.project import ProjectContext
from ..core.schema import Scene, VisualSpec
from ..providers.llm import generate_json
from ..renderers.manim_render import TEMPLATES, catalog, validate_params
from . import fill, load_workflow, read_prompt
from .topics import Topic, load_topic

log = get_logger()

WORKFLOW = "knowledge_explainer"

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "source": {"type": "string"}},
                "required": ["claim", "source"],
            },
        },
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string"},
                    "template": {"type": "string", "enum": list(TEMPLATES)},
                    "params": {"type": "object"},
                },
                "required": ["narration", "template", "params"],
            },
        },
    },
    "required": ["title", "description", "hashtags", "sources", "scenes"],
}


def _topic(ctx: ProjectContext) -> Topic:
    return load_topic(ctx.settings, str(ctx.project.options.get("topic") or "science"))


def _brief(ctx: ProjectContext) -> str:
    p = ctx.project
    if str(p.options.get("brief") or "").strip():
        return str(p.options["brief"]).strip()
    for name in ("brief.md", "source.md"):
        f = ctx.dir / "source" / name
        if f.is_file() and f.read_text(encoding="utf-8-sig").strip():
            return f.read_text(encoding="utf-8-sig").strip()
    return ""


_GLOSS = re.compile(r"\s*\[[^\]]*\]")
# on screen only word notes go; "[0, 10]" (an interval) stays
_WORD_GLOSS = re.compile(r"\s*\[[^\]]*[^\W\d_][^\]]*\]")


def _unglossed(value: object) -> object:
    """Drop `[gloss]` notes from on-screen text ("Ái Châu [Thanh Hóa]" -> "Ái Châu"), at any depth."""
    if isinstance(value, str):
        return " ".join(_WORD_GLOSS.sub("", value).split()) if "[" in value else value
    if isinstance(value, list):
        return [_unglossed(v) for v in value]
    if isinstance(value, dict):
        return {k: _unglossed(v) for k, v in value.items()}
    return value


def _scene_visual(i: int, s: dict, title: str, warnings: list[str]) -> VisualSpec:
    template = str(s.get("template") or "")
    raw = s.get("params")
    try:
        if isinstance(raw, str):  # some CLIs return nested objects as a JSON string
            try:
                raw = json.loads(raw)
            except ValueError:
                raise StudioError("params are not valid JSON", code="bad_manim_params") from None
        clean = raw if template == "formula" else _unglossed(raw)  # LaTeX uses brackets
        if clean != raw:
            warnings.append(f"scene_{i:02d}: removed [..] notes from the on-screen text")
        params = validate_params(template, clean)
    except StudioError as e:
        warnings.append(f"scene_{i:02d}: {e} -> using a title card")
        text = " ".join(str(s.get("narration") or title).split())
        template, params = "title", validate_params("title", {"title": text[:77] + "..." if len(text) > 80 else text})
    return VisualSpec(type="manim", template=template, params=params)


def _spoken(i: int, text: str, warnings: list[str]) -> str:
    """TTS reads brackets aloud: drop `[gloss]` notes some models add to the narration."""
    clean = " ".join(_GLOSS.sub("", text).split())
    if clean != " ".join(text.split()):
        warnings.append(f"scene_{i:02d}: removed [..] notes from the narration")
    return clean


def stage_explainer(ctx: ProjectContext, opts: dict) -> str:
    p = ctx.project
    if p.scenes and not opts.get("force"):
        return f"kept {len(p.scenes)} existing scenes"
    topic = _topic(ctx)
    brief = _brief(ctx)
    if not brief:
        raise ManualGateRequired("explainer", (
            "### Brief\n\nWrite what the video should explain in `source/brief.md` (the question, key facts, "
            "sources you trust), or create the project with `--brief \"...\"`, then re-run.\n\n"
            + "".join(f"- example: {b}\n" for b in topic.example_briefs)))
    lang = p.language
    n = int(p.options.get("scene_count", 6))
    scene_sec = float(p.options.get("scene_sec", 8))
    portrait = ctx.fmt.height > ctx.fmt.width
    photos = int(p.options.get("photos", 0))
    templates = list(topic.templates) + (["photo"] if photos > 0 and "photo" not in topic.templates else [])
    photo_rule = (f"Use the `photo` template for {photos} scene(s) where a real picture makes the fact credible "
                  "(a place, artefact, person, phenomenon): `query` in English with specific proper names; leave "
                  "out `file` and `credit`." if photos > 0 else "Do not use the `photo` template.")
    prompt = fill(read_prompt(ctx.settings, WORKFLOW, "script.md"), {
        "language": "Vietnamese" if lang == "vi" else "English",
        "topic": topic.label("en"), "tone": topic.tone, "guidance": topic.guidance.strip(),
        "forbidden": "\n".join(f"- {f}" for f in topic.forbidden) or "- (none)",
        "templates": catalog(templates), "scene_count": n, "photo_rule": photo_rule,
        # words per second of the profile at speed 1.0, times the project's voice speed
        "words": int(scene_sec * (2.6 if lang == "vi" else 2.4) * p.audio.speed),
        "orientation": "vertical 9:16 phone screen (keep texts short)" if portrait else "horizontal 16:9 screen",
        "sources_rule": ("Every number, date and factual claim must appear in `sources` with a real, checkable "
                         "source (publication, institution, book or URL). If unsure, leave the claim out."
                         if topic.require_sources else "List sources for facts that are not common knowledge."),
        "brief": brief,
    })
    wf = load_workflow(ctx.settings, WORKFLOW)
    data, provider = generate_json(ctx, "explainer", prompt, SCRIPT_SCHEMA, chain=wf.get("llm_chain"),
                                   force=bool(opts.get("force")))
    warnings: list[str] = []
    title = str(data.get("title") or "").strip()
    scenes = []
    for i, s in enumerate(data.get("scenes") or [], start=1):
        visual = _scene_visual(i, s, title, warnings)
        if visual.template not in templates:
            log.info("[explainer] scene_%02d uses %s (not in the %s topic list)", i, visual.template, topic.id)
        scenes.append(Scene(scene_id=f"scene_{i:02d}", narration=_spoken(i, str(s.get("narration") or ""), warnings),
                            visual=visual))
    if not scenes:
        raise StudioError("the explainer answer has no scenes", code="llm_bad_output")
    for w in warnings:
        log.warning("[explainer] %s", w)
    p.scenes = scenes
    p.title = p.title or title
    desc = p.description or str(data.get("description") or "").strip()
    note = topic.disclaimer_for(lang)
    if note and note not in desc:
        desc = f"{desc}\n\n{note}".strip()
    p.description = desc
    tags = [h if h.startswith("#") else f"#{h}" for h in data.get("hashtags") or []]
    p.hashtags = p.hashtags or list(dict.fromkeys(tags + topic.hashtags.get(lang, [])))
    p.options["sources"] = [{"claim": str(x.get("claim", "")), "source": str(x.get("source", ""))}
                            for x in data.get("sources") or []]
    p.options.setdefault("palette", topic.palette)
    if "backdrop" in topic.options:
        p.options.setdefault("backdrop", topic.options["backdrop"])
    if note and topic.disclaimer_on_screen:
        p.options.setdefault("on_screen_note", note)
    p.options["reviewed"] = False  # new script -> needs a new review
    ctx.save()
    extra = f", {len(warnings)} scene(s) fell back to a title card" if warnings else ""
    return f"{len(scenes)} scenes via {provider}{extra}"


def _have_file(ctx: ProjectContext, ref: str | None) -> bool:
    if not ref:
        return False
    try:
        return ctx.resolve(ref, what="photo").is_file()
    except StudioError:
        return False


def stage_images(ctx: ProjectContext, opts: dict) -> str:
    """Fetch a freely licensed Commons photo for each `photo` scene (kept unless --force); none -> title card."""
    from ..core.errors import ProviderUnavailable
    from ..providers.images import find_photo

    p = ctx.project
    credits = {c.get("scene_id"): c for c in p.options.get("image_credits") or []}
    used = {c.get("title") for c in credits.values()}
    got, fell = 0, []
    for s in p.scenes:
        v = s.visual
        if v.type != "manim" or v.template != "photo":
            continue
        params = dict(v.params or {})
        if _have_file(ctx, params.get("file")) and not opts.get("force"):
            continue
        stem = ctx.work / "images" / s.scene_id
        stem.parent.mkdir(parents=True, exist_ok=True)
        try:
            hit = find_photo(ctx.settings.path("cache"), params["query"], stem, avoid=used)
        except ProviderUnavailable as e:
            log.warning("[images] %s: %s", s.scene_id, e)
            hit = None
        if hit is None:
            text = params.get("caption") or " ".join(s.narration.split()) or p.title or "..."
            v.template, v.params = "title", validate_params("title", {"title": text[:77] + "..." if len(text) > 80
                                                                       else text})
            credits.pop(s.scene_id, None)
            fell.append(s.scene_id)
            continue
        path, photo = hit
        rel = path.relative_to(ctx.dir).as_posix()
        params.update(file=rel, credit=photo.credit())
        v.params = validate_params("photo", params)
        used.add(photo.title)
        credits[s.scene_id] = {"scene_id": s.scene_id, "title": photo.title, "author": photo.author,
                               "license": photo.license, "license_url": photo.license_url, "page": photo.page,
                               "file": rel, "query": params["query"]}
        got += 1
    p.options["image_credits"] = [credits[s.scene_id] for s in p.scenes if s.scene_id in credits]
    ctx.save()
    for sid in fell:
        log.warning("[images] %s: no free photo found -> title card", sid)
    if not got and not fell:
        return "no new photos needed"
    return f"{got} photo(s) from Wikimedia Commons" + (f", {len(fell)} fell back to a title card" if fell else "")


def stage_review(ctx: ProjectContext, opts: dict) -> str:
    if ctx.settings.get("reviews.required", True):
        from ..core.user_review import checkpoint

        checkpoint(ctx.dir, "script")
        return "user script checkpoint accepted"
    p = ctx.project
    topic = _topic(ctx)
    if not topic.review_required or p.options.get("review") is False:
        return "review not required"
    if p.options.get("reviewed") is True:
        return "approved"
    sources = p.options.get("sources") or []
    lines = [f"### Review the script ({topic.label(p.language)})", "",
             "Nothing is voiced or rendered until you approve. Check every claim, fix `project.json` "
             "(narration, `visual.params`, `options.sources`) if needed, then run:", "",
             f'    studio approve "{ctx.dir}"', "", "and re-run `studio run`.", "", "#### Scenes", ""]
    for s in p.scenes:
        lines.append(f"- **{s.scene_id}** [{s.visual.template or s.visual.type}] {s.narration}")
    images = p.options.get("image_credits") or []
    if images:
        lines += ["", "#### Photos (Wikimedia Commons)", ""]
        lines += [f"- **{c['scene_id']}** `{c['file']}` — {c['title']} · {c['author']} · {c['license']} — {c['page']}"
                  for c in images]
    lines += ["", "#### Sources", ""]
    if sources:
        lines += [f"- {x.get('claim')} — {x.get('source')}" for x in sources]
    else:
        lines.append("- (none given)" + (" — this topic requires sources: add them to options.sources"
                                         if topic.require_sources else ""))
    lines += ["", "#### Checklist", "",
              "- [ ] every number, date and name is correct and matches a source",
              "- [ ] quotes are real and attributed",
              "- [ ] numbers on screen (params) match the narration"]
    if images:
        lines.append("- [ ] each photo shows what its caption and narration say (else change `params.query` and "
                     "re-run with `--from images --force`, or put your own file in `params.file`)")
    lines += [f"- [ ] not: {f}" for f in topic.forbidden]
    note = topic.disclaimer_for(p.language)
    if note:
        lines.append(f"- [ ] disclaimer is in the description{' and on screen' if topic.disclaimer_on_screen else ''}: "
                     f"\"{note}\"")
    raise ManualGateRequired("review", "\n".join(lines) + "\n")


STAGES = {"explainer": stage_explainer, "images": stage_images, "review": stage_review}
