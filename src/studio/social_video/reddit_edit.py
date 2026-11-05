"""Shorts pacing and publish handoff; no algorithm/retention guarantees."""

from ..core.errors import ManualGateRequired


def partition(groups, voiced, max_seconds=180, *, vi=None, target_seconds=90):
    """Keep a complete story together when it fits; split at reviewed suspense beats."""
    import re

    from .reddit import sentences

    budget = max_seconds - 12.35  # hook <= 5 s + closing question <= 6 s + end/scare room
    preferred = set()
    if vi:
        paragraphs = vi.get("paragraphs", [])
        preferred = {
            sentences(paragraphs[i])[-1]
            for i in vi.get("suspense_breaks", [])
            if isinstance(i, int) and 0 <= i < len(paragraphs) and sentences(paragraphs[i])
        }
    items = []
    index = 0
    for group in groups:
        seconds = sum(t for _, t in voiced[index : index + len(group)])
        if seconds > budget:
            raise ManualGateRequired(
                "reddit_split", "Một câu/đoạn quá dài; chia ở nút thắt trước khi duyệt giọng, không ép tốc độ."
            )
        items.append((group, index, seconds))
        index += len(group)
    parts = []
    while items:
        if sum(x[2] for x in items) <= budget:
            parts.append([(g, k) for g, k, t in items])
            break
        choices = []
        used = 0
        for i, (group, _k, seconds) in enumerate(items):
            used += seconds
            if used > budget:
                break
            dramatic = group[-1] in preferred or bool(
                re.search(r"bỗng|chợt|phía sau|tiếng gọi|vừa mở|nhưng|[?…]$", group[-1], re.I)
            )
            score = abs(used - min(target_seconds, budget * 0.9)) + (0 if dramatic else 40)
            if group[-1] in preferred:
                score -= 25
            if used < min(target_seconds * 0.55, budget * 0.5):
                score += 100
            choices.append((score, i + 1))
        if not choices:
            raise ManualGateRequired("reddit_split", "Chưa có điểm ngắt phù hợp.")
        cut = min(choices)[1]
        parts.append([(g, k) for g, k, t in items[:cut]])
        items = items[cut:]
    return parts


def plan(groups, voiced, max_seconds=180, *, vi=None, target_seconds=90):
    parts = partition(groups, voiced, max_seconds, vi=vi, target_seconds=target_seconds)
    return [
        {
            "part": i + 1,
            "opener": p[0][0][0],
            "spoken_seconds": round(sum(voiced[k + j][1] for g, k in p for j in range(len(g))), 3),
            "sentences": [k + j for g, k in p for j in range(len(g))],
            "part_number_spoken": False,
            "closing_line": p[-1][0][-1],
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
