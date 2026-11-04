"""Shorts pacing and publish handoff; no algorithm/retention guarantees."""

from ..core.errors import ManualGateRequired


def partition(groups, voiced, max_seconds=75):
    # At most 5s opening, 0.35s end card, 1.6s optional approved scare.
    budget = max_seconds - 6.95
    parts = []
    cur = []
    used = 0.0
    index = 0
    for g in groups:
        length = sum(t for _, t in voiced[index : index + len(g)])
        if length > budget:
            raise ManualGateRequired(
                "reddit_split",
                "Một nhóm lời đọc vượt thời lượng phần; sửa/chia câu trước khi duyệt giọng, không ép tăng tốc tùy ý.",
            )
        if cur and used + length > budget:
            parts.append(cur)
            cur = []
            used = 0.0
        cur.append((g, index))
        used += length
        index += len(g)
    if cur:
        parts.append(cur)
    return parts


def plan(groups, voiced, max_seconds=75):
    parts = partition(groups, voiced, max_seconds)
    return [
        {
            "part": i + 1,
            "opener": p[0][0][0],
            "spoken_seconds": round(sum(voiced[k + j][1] for g, k in p for j in range(len(g))), 3),
            "sentences": [k + j for g, k in p for j in range(len(g))],
            "part_number_spoken": False,
        }
        for i, p in enumerate(parts)
    ]


def hook_texts(vi, parts):
    import re

    from ..core.errors import ValidationError

    hooks = []
    for i, p in enumerate(parts):
        supplied = vi.get("part_hooks", [])
        hook = (supplied[i] if i < len(supplied) else vi.get("hook", "") if i == 0 else "").strip()
        opener = hook or p[0][0][0]
        if re.search(r"(?i)\bphần\s+(?:\d+|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười)\b", " ".join(opener.split()[:15])):
            raise ValidationError("Không đọc số phần trong câu mở đầu", code="reddit_hook")
        hooks.append(hook if hook != p[0][0][0] else "")
    return hooks


def approved_audio(folder, expected_sentences):
    """Render only the actual clips offered at checkpoint two; never synthesize here."""
    from pathlib import Path

    from .util import media_duration, read_json

    manifest = read_json(folder / "voice_manifest.json", {})
    body = manifest.get("body", [])
    if len(body) != expected_sentences or "hooks" not in manifest:
        raise ManualGateRequired("voice_assets", "Chuẩn bị và nghe duyệt toàn bộ lời đọc trước khi dựng.")

    def clip(item):
        if item is None:
            return None
        path = Path(item["path"])
        if not path.is_file() or abs(media_duration(path) - item["seconds"]) > 0.05:
            raise ManualGateRequired(
                "voice_assets", "Tệp lời đọc thay đổi; cần chuẩn bị lại gói nghe, không tự gen khi dựng."
            )
        return path, item["seconds"]

    return [clip(item) for item in body], [clip(item) for item in manifest["hooks"]]
