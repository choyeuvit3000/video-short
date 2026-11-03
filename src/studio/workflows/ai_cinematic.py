"""L1 ai_cinematic: the original spec - storyboard by an AI CLI, keyframes/clips made by hand
(ChatGPT images, Google Flow), fixed scene timing, FFmpeg assembly.

Stages: storyboard -> media -> (validate, voice, render, qc, package)
  storyboard : scenes from options.brief / source/brief.md via the LLM chain (skipped if scenes exist)
  media      : manual gate - lists every missing clip/image with its prompt and target file name
"""

from __future__ import annotations

from ..core.errors import ManualGateRequired
from ..core.logging_utils import get_logger
from ..core.project import ProjectContext
from ..core.schema import Scene, VisualSpec
from ..providers.llm import generate_json
from . import fill, load_workflow, read_prompt

log = get_logger()

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")

STORYBOARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "style": {"type": "string", "description": "global visual style applied to every prompt"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "duration_sec": {"type": "number"},
                    "narration": {"type": "string"},
                    "image_prompt": {"type": "string"},
                    "video_prompt": {"type": "string"},
                },
                "required": ["duration_sec", "narration", "image_prompt", "video_prompt"],
            },
        },
    },
    "required": ["title", "description", "hashtags", "style", "scenes"],
}


def stage_storyboard(ctx: ProjectContext, opts: dict) -> str:
    p = ctx.project
    if p.scenes and not opts.get("force"):
        return f"kept {len(p.scenes)} existing scenes"
    brief_file = ctx.dir / "source" / "brief.md"
    brief = p.options.get("brief") or (brief_file.read_text(encoding="utf-8-sig") if brief_file.exists() else "")
    if not brief.strip():
        raise ManualGateRequired("storyboard", (
            "### Brief\n\nWrite the video idea in `source/brief.md` (topic, mood, characters, length), "
            "or add scenes to project.json by hand, then re-run.\n"))
    n = int(p.options.get("scene_count", 6))
    clip_sec = float(p.options.get("clip_sec", 8))
    prompt = fill(read_prompt(ctx.settings, "ai_cinematic", "storyboard.md"), {
        "language": "Vietnamese" if p.language == "vi" else "English",
        "scene_count": n, "clip_sec": clip_sec, "brief": brief.strip(),
    })
    wf = load_workflow(ctx.settings, "ai_cinematic")
    data, provider = generate_json(ctx, "storyboard", prompt, STORYBOARD_SCHEMA, chain=wf.get("llm_chain"),
                                   force=bool(opts.get("force")))
    style = data.get("style", "").strip()
    scenes = []
    for i, s in enumerate(data["scenes"], start=1):
        sid = f"scene_{i:02d}"
        dur = min(max(float(s.get("duration_sec") or clip_sec), 2.0), clip_sec)
        img = s["image_prompt"] + (f". Style: {style}" if style else "")
        scenes.append(Scene(scene_id=sid, narration=s.get("narration", ""), duration_sec=dur,
                            image_prompt=img, video_prompt=s.get("video_prompt"),
                            visual=VisualSpec(type="clip", path=f"clips/{sid}.mp4")))
    p.scenes = scenes
    p.title = p.title or data.get("title", "")
    p.description = p.description or data.get("description", "")
    p.hashtags = p.hashtags or [h if h.startswith("#") else f"#{h}" for h in data.get("hashtags", [])]
    ctx.save()
    return f"{len(scenes)} scenes via {provider}"


def stage_media(ctx: ProjectContext, opts: dict) -> str:
    p = ctx.project
    missing = []
    switched = 0
    for s in p.scenes:
        v = s.visual
        if v.type not in ("clip", "still") or not v.path:
            continue
        if ctx.resolve(v.path).is_file():
            continue
        if v.type == "clip" and p.options.get("allow_still_fallback", True):
            still = next((ctx.dir / "images" / f"{s.scene_id}{e}" for e in IMAGE_EXT
                          if (ctx.dir / "images" / f"{s.scene_id}{e}").is_file()), None)
            if still:
                log.warning("[media][%s] no clip yet -> using %s with Ken Burns", s.scene_id, still.name)
                s.visual = VisualSpec(type="still", path=still.relative_to(ctx.dir).as_posix(),
                                      overlay=v.overlay, overlay_until_sec=v.overlay_until_sec)
                switched += 1
                continue
        missing.append(s)
    if switched:
        ctx.save()
    if not missing:
        return f"all media present ({switched} still fallback(s))"
    lines = [f"### Media ({len(missing)} missing)", "",
             "Create each file by hand (ChatGPT image -> Google Flow clip), save it at the path shown, "
             "then re-run `studio run`. A `images/<scene_id>.png` alone is enough for a Ken Burns fallback.", ""]
    for s in missing:
        lines += [f"- [ ] **{s.scene_id}** -> `{s.visual.path}` ({s.duration_sec or '?'}s)"]
        if s.image_prompt:
            lines.append(f"  - image prompt: {s.image_prompt}")
        if s.video_prompt:
            lines.append(f"  - video prompt: {s.video_prompt}")
    if not any(s.image_prompt or s.video_prompt for s in missing):
        lines.append("\n(no prompts in project.json - write them or run the storyboard stage)")
    raise ManualGateRequired("media", "\n".join(lines) + "\n")


STAGES = {"storyboard": stage_storyboard, "media": stage_media}
