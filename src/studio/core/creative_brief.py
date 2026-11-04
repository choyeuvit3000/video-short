"""Clarify -> propose -> static preflight -> approve -> bounded generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import ManualGateRequired, ValidationError


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = ""
    audience: str = ""
    platform: Literal["shorts", "tiktok", "reels", "private"] = "private"
    detail: Literal["concise", "balanced", "detailed"] = "balanced"
    target_seconds: int = Field(default=60, ge=5, le=7200)
    source_policy: Literal["faithful", "summary"] = "faithful"
    narration: Literal["captions_only", "verbatim", "summary"] = "captions_only"
    voice: str = "omnivoice-vi-thaison"
    background: Literal["keep", "blur", "minecraft"] = "keep"
    subtitles: Literal["none", "sentence", "highlight"] = "none"
    memes: Literal["none", "approved_plan_only"] = "none"
    pacing: Literal["calm", "normal", "brisk"] = "normal"
    must_include: str = ""
    must_avoid: str = ""
    reference: str = ""
    max_full_renders: int = Field(default=1, ge=1, le=3)


LABELS = {
    "goal": "Mục tiêu/thông điệp chính",
    "audience": "Người xem là ai, họ đã biết gì?",
    "platform": "Nền tảng",
    "detail": "Mức chi tiết",
    "target_seconds": "Thời lượng mong muốn (giây)",
    "source_policy": "Giữ nguyên ý hay tóm tắt?",
    "narration": "Phần nào được đọc?",
    "voice": "ID giọng đã qua QC",
    "background": "Nền",
    "subtitles": "Phụ đề",
    "memes": "Meme theo plan đã duyệt hay không?",
    "pacing": "Nhịp dựng",
    "must_include": "Thông tin bắt buộc giữ",
    "must_avoid": "Nội dung/hiệu ứng cần tránh",
    "reference": "Video mẫu/phong cách tham chiếu",
    "max_full_renders": "Số lượt render toàn bộ tối đa",
}


def _read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def mode_for(folder):
    p = _read(folder / "project.json", {})
    if p:
        return p["workflow"]
    if (folder / "posts.json").is_file():
        return "threads"
    if (folder / "vi.json").is_file():
        return "reddit"
    raise ValidationError("Prepare/capture a source or create a project first", code="brief_source_missing")


def inputs(folder, mode):
    project = _read(folder / "project.json", {})
    spec = {
        "mode": mode,
        "source": project.get("source"),
        "video": project.get("video"),
        "audio": project.get("audio"),
        "scenes": [
            {k: s.get(k) for k in ("scene_id", "narration", "duration_sec", "visual")}
            for s in project.get("scenes", [])
        ],
    }
    files = {}
    for rel in (
        "posts.json",
        "source.json",
        "vi.json",
        "source/source.md",
        "source/brief.md",
        "work/script.json",
        "merged_plan.json",
    ):
        p = folder / rel
        if p.is_file():
            files[rel] = _sha(p)
    # Source screenshots, media, references and scene overlays are bound to approval.
    posts = _read(folder / "posts.json", [])
    refs = []
    for post in posts:
        refs += (
            post.get("parts", [])
            + [m["file"] for m in post.get("media", [])]
            + [c["image"] for c in post.get("comments", []) if c.get("image")]
        )
    for s in project.get("scenes", []):
        refs += [s.get("visual", {}).get(k) for k in ("path", "overlay")]
    for ref in refs:
        if not ref or str(ref).startswith("asset:"):
            continue
        p = folder / ref
        if p.is_file():
            files[str(ref)] = _sha(p)
    spec["files"] = files
    return spec


def recommendation(folder, mode):
    project = _read(folder / "project.json", {})
    b = Brief().model_dump()
    from ..voices import load_registry
    from .config import get_settings

    b["voice"] = load_registry(get_settings()).default_for(project.get("language", "vi"), mode).id
    b.update(
        goal="Giữ đúng thông tin nguồn, trình bày rõ và dễ xem",
        audience="Người Việt xem video ngắn",
        narration="verbatim" if mode == "reddit" else "captions_only",
        background="blur" if mode == "threads" else "minecraft" if mode == "reddit" else "keep",
        reference="approved-merged-v1" if mode == "threads" else "",
    )
    if project:
        b["voice"] = project.get("audio", {}).get("voice_profile") or b["voice"]
        b["subtitles"] = "none" if project.get("video", {}).get("subtitle_mode") == "none" else "sentence"
    from .voice_policy import blocked

    if blocked("", b["voice"], {"voice": b["voice"]}):
        b["voice"] = "omnivoice-vi-thaison"
    return b


def prepare(folder: Path, answers=None, *, accept_recommendations=False):
    folder = folder.resolve()
    mode = mode_for(folder)
    path = folder / "video_brief.json"
    previous = _read(path, {})
    rec = recommendation(folder, mode)
    values = dict(previous.get("answers", {}))
    if "voice" not in values:
        values["voice"] = rec["voice"]
    if accept_recommendations:
        values = {**rec, **values}
    values.update(answers or {})
    b = Brief.model_validate(values)
    values = b.model_dump()
    missing = [k for k in ("goal", "audience") if not values[k].strip()]
    from .voice_policy import assert_not_blocked

    assert_not_blocked("", values["voice"], {"voice": values["voice"]})
    source = inputs(folder, mode)
    fp = _hash([source, values])
    unchanged = previous.get("approved_fingerprint") == fp
    result = {
        "version": 1,
        "mode": mode,
        "answers": values,
        "recommendations": rec,
        "missing": missing,
        "fingerprint": fp,
        "approved_fingerprint": previous.get("approved_fingerprint"),
        "status": "APPROVED" if unchanged and not missing else "DRAFT",
        "reviewer": previous.get("reviewer"),
        "questions": [{"field": k, "question": LABELS[k], "recommended": rec[k]} for k in missing],
    }
    _write(path, result)
    lines = ["# Brief cần chốt trước khi gen", "", f"Mode: {mode}", f"Trạng thái: {result['status']}", ""]
    for k, v in values.items():
        lines.append(f"- {LABELS[k]}: {v if str(v).strip() else '(chưa rõ)'}")
    lines += [
        "",
        "## Đề xuất",
        "- Chốt nội dung và nguồn trước; không tự bịa chi tiết.",
        "- Nam trầm miền Nam; Edge/Mai Anh bị cấm. Giọng chưa qua QC không dùng production.",
        "- Preview storyboard tĩnh trước; chỉ render lại cảnh thay đổi.",
        f"- Ngân sách {values['max_full_renders']} lượt full render cho phiên bản brief đã duyệt.",
        "- Thời lượng chỉ là mục tiêu: giữ đủ clip gốc nếu chưa được phép cắt.",
    ]
    if previous.get("approved_fingerprint") and not unchanged:
        lines += ["", "Nguồn/plan/brief đã thay đổi: cần xem và duyệt lại, không tự gen."]
    (folder / "VIDEO_BRIEF.md").write_text("\n".join(lines), encoding="utf-8")
    _write(folder / "interview_questions.json", result["questions"])
    return result


def approve(folder: Path, reviewer: str):
    data = prepare(folder)
    if data["missing"]:
        raise ValidationError("Unanswered brief fields: " + ", ".join(data["missing"]), code="brief_incomplete")
    if not reviewer.strip():
        raise ValidationError("Name the person approving this concrete brief", code="brief_incomplete")
    project = folder / "project.json"
    if project.is_file():
        from ..voices import load_registry
        from .project import ProjectContext

        ctx = ProjectContext(folder)
        b = data["answers"]
        load_registry(ctx.settings).get(b["voice"])
        ctx.project.audio.voice_profile = b["voice"]
        ctx.project.audio.speed = {"calm": 0.95, "normal": 1.0, "brisk": 1.12}[b["pacing"]]
        ctx.project.video.subtitle_mode = "none" if b["subtitles"] == "none" else "burn_in"
        if ctx.project.workflow == "story_reader":
            ctx.project.options["rewrite"] = "none" if b["source_policy"] == "faithful" else "llm"
        ctx.save()
        data = prepare(folder)
    data.update(status="APPROVED", approved_fingerprint=data["fingerprint"], reviewer=reviewer)
    _write(folder / "video_brief.json", data)
    return prepare(folder)


def ensure_ready(folder: Path):
    data = prepare(folder)
    if data["status"] != "APPROVED":
        raise ManualGateRequired(
            "creative_brief",
            f"Read {folder / 'VIDEO_BRIEF.md'} and answer interview_questions.json. "
            f'Run studio brief "{folder}" --interactive, review studio preflight, then '
            f'studio brief "{folder}" --approve --reviewer NAME. No voice/full render started.',
        )
    return data


def reserve_render(folder: Path, signature: str, *, reset_reason=None):
    brief = ensure_ready(folder)
    path = folder / "generation_budget.json"
    ledger = _read(path, {"attempts": []})
    if reset_reason:
        ledger.setdefault("resets", []).append({"reason": reset_reason, "previous": ledger["attempts"]})
        ledger["attempts"] = []
    fp = brief["approved_fingerprint"]
    used = sum(a["brief"] == fp for a in ledger["attempts"])
    if used >= brief["answers"]["max_full_renders"]:
        raise ManualGateRequired(
            "render_budget",
            "Full-render budget exhausted. Inspect QC, fix only changed scenes, and explicitly grant another attempt "
            "with studio brief --reset-budget --reason REASON. --force does not bypass the budget.",
        )
    ledger["attempts"].append({"brief": fp, "signature": signature, "status": "STARTED"})
    _write(path, ledger)


def preflight(folder: Path):
    """Static, inexpensive storyboard: no model calls, voice or full video encoding."""
    from PIL import Image, ImageDraw, ImageFont

    data = prepare(folder)
    project = _read(folder / "project.json", {})
    texts = [s.get("narration", "") for s in project.get("scenes", [])]
    if not texts:
        posts = _read(folder / "posts.json", [])
        texts = [t for p in posts for t in p.get("part_texts", [])] or _read(folder / "vi.json", {}).get(
            "paragraphs", []
        )
    texts = texts or ["Chưa có kịch bản/cảnh. Chốt brief trước, rồi chỉ chạy các bước chuẩn bị nội dung."]
    import textwrap

    pages = []
    for start in range(0, len(texts), 8):
        canvas = Image.new("RGB", (960, 720), "#15191f")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
        for n, text in enumerate(texts[start : start + 8]):
            x = (n % 4) * 240
            y = (n // 4) * 360
            draw.rectangle((x + 8, y + 8, x + 232, y + 350), fill="#272f3a")
            draw.multiline_text(
                (x + 18, y + 22),
                f"Scene {start + n + 1}\n\n" + "\n".join(textwrap.wrap(text, 22)[:12]),
                font=font,
                fill="white",
                spacing=5,
            )
        path = folder / f"preflight_{start // 8 + 1:02d}.jpg"
        canvas.save(path)
        pages.append(path.name)
    words = sum(len(t.split()) for t in texts)
    from ..voices import load_registry
    from .config import get_settings

    profile = load_registry(get_settings()).get(data["answers"]["voice"])
    rate = float(profile.params.get("target_space_tokens_per_second", 3.2))
    pace = {"calm": 0.95, "normal": 1.0, "brisk": 1.12}[data["answers"]["pacing"]]
    seconds = words / (rate * float(profile.params.get("speed", 1.0)) * pace)
    report = {
        "brief_status": data["status"],
        "scenes": len(texts),
        "spoken_words": words,
        "estimated_speech_seconds": round(seconds, 1),
        "speech_rate_source": "profile" if "target_space_tokens_per_second" in profile.params else "rough default",
        "target_seconds": data["answers"]["target_seconds"],
        "preview_kind": "text storyboard, not pixel-accurate final layout",
        "pages": pages,
        "cost": "no AI/TTS/full-render calls",
        "warnings": [],
    }
    if seconds > data["answers"]["target_seconds"] * 1.2:
        report["warnings"].append(
            "Narration likely exceeds target duration; shorten text or approve a longer video before generating voice"
        )
    _write(folder / "preflight.json", report)
    return report


def apply_social(folder, cfg):
    data = ensure_ready(folder)
    b = data["answers"]
    from ..voices import load_registry
    from .config import get_settings

    reg = load_registry(get_settings())
    profile = reg.get(b["voice"])
    if profile.provider not in {"vieneu", "omnivoice"}:
        raise ValidationError("Social mode requires a reviewed local voice", code="brief_voice")
    engine = profile.provider
    cfg["tts"]["engines"] = [engine]
    options = cfg["tts"].setdefault(engine, {})
    options["profile"] = profile.id
    if engine == "vieneu":
        options["voice"] = profile.params["voice"]
    options["speed"] = {"calm": 0.95, "normal": 1.0, "brisk": 1.15}[b["pacing"]]
    cfg["reddit"]["background_family"] = "minecraft" if b["background"] == "minecraft" else "any"
    cfg["reddit"]["jumpscares_enabled"] = b["memes"] != "none"
    if data["mode"] == "reddit" and b["narration"] != "verbatim":
        raise ValidationError(
            "Edit and approve vi.json before summarizing; Reddit reads approved text verbatim", code="brief_conflict"
        )
    if data["mode"] == "threads":
        beats = _read(folder / "merged_plan.json", {}).get("beats", [])
        if b["memes"] == "none" and any(x.get("image_id") or x.get("sound_id") for x in beats):
            raise ValidationError(
                "Brief forbids memes; remove them from plan or approve approved_plan_only", code="brief_conflict"
            )
        if b["narration"] != "captions_only":
            raise ValidationError(
                "Threads narration must use captions or an explicit edited narration/beat plan, not an invented story",
                code="brief_conflict",
            )
        if b["subtitles"] == "highlight":
            raise ValidationError(
                "Native word-highlight timing is estimated; choose sentence/none until real alignment is enabled",
                code="brief_conflict",
            )
        cfg["story"]["subtitles"] = b["subtitles"] != "none"
        cfg["story"]["background"] = "blur" if b["background"] in ("keep", "blur") else "minecraft"
    return data


def finish_render(folder, success, outputs=()):
    path = folder / "generation_budget.json"
    ledger = _read(path, {"attempts": []})
    if ledger["attempts"]:
        ledger["attempts"][-1].update(status="COMPLETE" if success else "FAILED", outputs=[str(p) for p in outputs])
        _write(path, ledger)


def begin_social(folder, cfg):
    data = apply_social(folder, cfg)
    from .voice_policy import assert_social_config, signature, social_profile

    assert_social_config(cfg["tts"])  # before reading caches or starting work
    key = _hash(
        [
            data["approved_fingerprint"],
            signature(social_profile(cfg["tts"])[0]),
            {k: cfg.get(k) for k in ("tts", "video", "story", "reddit", "fonts", "bgm")},
        ]
    )
    cache = _read(folder / "native_render_cache.json", {})
    items = cache.get("outputs", [])
    if (
        cache.get("key") == key
        and items
        and all(Path(i["path"]).is_file() and _sha(Path(i["path"])) == i["sha256"] for i in items)
    ):
        return key, [Path(i["path"]) for i in items]
    reserve_render(folder, key)
    return key, []


def complete_social(folder, key, outputs):
    _write(
        folder / "native_render_cache.json",
        {"key": key, "outputs": [{"path": str(p), "sha256": _sha(p)} for p in outputs]},
    )
    finish_render(folder, True, outputs)
