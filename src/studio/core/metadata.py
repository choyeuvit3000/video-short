"""output/metadata.md - title, description, hashtags, AI disclosure, source credit, asset sources."""

from __future__ import annotations

import json

from .project import ProjectContext

DISCLOSURE = {
    "vi": "Video có sử dụng nội dung do AI tạo (giọng đọc/hình ảnh). Hãy bật nhãn \"AI-generated\" khi đăng.",
    "en": "This video contains AI-generated content (voice/visuals). Turn on the platform's AI-generated label.",
}


def write_metadata(ctx: ProjectContext) -> str:
    p = ctx.project
    lines = [f"# {p.title or p.project_id}", ""]
    lines += ["## Description", "", p.description or "-", ""]
    if p.hashtags:
        lines += ["## Hashtags", "", " ".join(p.hashtags), ""]
    lines += ["## Platforms", "", ", ".join(p.platforms), ""]
    if p.ai_generated:
        lines += ["## AI disclosure", "", DISCLOSURE[p.language], ""]
    src = p.source
    if src.type != "none":
        lines += ["## Source / credit", ""]
        if src.credit_text:
            lines.append(src.credit_text)
        for k in ("platform", "community", "author", "url"):
            v = getattr(src, k)
            if v:
                lines.append(f"- {k}: {v}")
        lines.append("")
    sources = p.options.get("sources") or []
    if sources:  # knowledge videos: the references behind the claims, ready to paste under the video
        lines += ["## Sources", ""]
        lines += [f"- {x.get('claim', '')}: {x.get('source', '')}" for x in sources if isinstance(x, dict)]
        lines.append("")
    lines += ["## Assets used", ""]
    seen = set()
    refs = [p.video.background, p.audio.background_music] + [s.visual.path for s in p.scenes] + \
           [s.visual.overlay for s in p.scenes]
    for ref in refs:
        if ref and ref not in seen and ref != "gradient" and not ref.startswith("color:"):
            seen.add(ref)
            note = next((s.source_note for s in p.scenes if s.visual.path == ref and s.source_note), "")
            lines.append(f"- {ref}" + (f" — {note}" if note else ""))
    if not seen:
        lines.append("- (generated in-app only)")
    lines.append("")
    voice = _voice_used(ctx)
    if voice:
        lines += ["## Voice", "", f"- {voice}", ""]
    cost = ctx.dir / "cost.json"
    if cost.exists():
        total = json.loads(cost.read_text(encoding="utf-8")).get("total_usd", 0)
        lines += ["## Cost", "", f"- paid API spend: ${total:.4f}", ""]
    text = "\n".join(lines)
    (ctx.output / "metadata.md").write_text(text, encoding="utf-8")
    return text


def _voice_used(ctx: ProjectContext) -> str | None:
    try:
        tl = ctx.load_timeline()
    except Exception:
        return None
    return tl.get("voice_profile")
