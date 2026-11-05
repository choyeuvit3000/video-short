"""Read-only draft linting; semantic approval and real speech timing remain separate."""

import hashlib
import json
import re
from pathlib import Path


def sentences(text):
    return [
        m.group().strip(" \t\r\n“”\"'")
        for m in re.finditer(r"[^.!?…]+(?:[.!?…]+|$)", text)
        if m.group().strip(" \t\r\n“”\"'")
    ]


def review_draft(draft):
    if draft.get("fiction") is not True:
        raise ValueError("This writing check is for explicitly labelled fiction, not rewriting a factual source")
    episodes = draft.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("Need at least one draft episode")
    results = []
    for i, episode in enumerate(episodes, 1):
        text = episode.get("narration", "")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Episode {i} has no narration")
        chunks = sentences(text)
        hook = chunks[0] if chunks else ""
        warnings = []
        if len(hook.split()) >= 15:
            warnings.append("HOOK_LONG: shorten/review the opening; count is not actual duration")
        if re.search(r"(?i)\b(?:tập trước|phần trước|như đã kể|như tôi đã kể|ở tập|ở phần)\b", hook):
            warnings.append("RECAP_OPENING: replace recap with a self-contained event")
        if re.search(r"\d", text):
            warnings.append("SPOKEN_DIGITS: write numbers/symbols as spoken Vietnamese before TTS")
        anchor = episode.get("sensory_anchor", "")
        pos = text.find(anchor) if isinstance(anchor, str) and anchor.strip() else -1
        if pos < 0:
            warnings.append("SENSORY_ANCHOR_MISSING: mark an exact sound/smell/touch phrase in the text")
        start = episode.get("climax_start", "")
        a = text.find(start) if isinstance(start, str) and start.strip() else -1
        end = episode.get("climax_end")
        b = text.find(end, a) if isinstance(end, str) and end.strip() and a >= 0 else len(text)
        if a < 0 or b < a:
            warnings.append("CLIMAX_NOT_MARKED: identify the dramatic region before checking sentence rhythm")
            long_lines = []
        else:
            long_lines = [
                {"text": sentence, "units": len(sentence.split())}
                for sentence in sentences(text[a:b])
                if len(sentence.split()) >= 15
            ]
            if long_lines:
                warnings.append("CLIMAX_LONG_SENTENCES: consider full stops; do not split automatically")
        results.append(
            {
                "episode": i,
                "title": episode.get("title", str(i)),
                "space_separated_units": len(text.split()),
                "hook": hook,
                "hook_units": len(hook.split()),
                "sensory_anchor": anchor,
                "sensory_units_before": len(text[:pos].split()) if pos >= 0 else None,
                "hook_first_three_seconds": "PENDING_ACTUAL_SPEECH_TIMING",
                "sensory_first_fifteen_seconds": "PENDING_ACTUAL_SPEECH_TIMING",
                "standalone_hook_semantics": "CREATOR_REVIEW_REQUIRED",
                "long_climax_sentences": long_lines,
                "warnings": warnings,
            }
        )
    fingerprint = hashlib.sha256(json.dumps(draft, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        "version": 1,
        "draft_sha256": fingerprint,
        "status": "DRAFT_REVIEW_REQUIRED",
        "count_method": "whitespace-separated units, not Vietnamese lexical words",
        "actual_duration": "NOT_MEASURED",
        "creator_approved": False,
        "episodes": results,
    }


def write_review(source, output=None):
    source = Path(source)
    output = Path(output) if output else source.with_suffix(".editorial.json")
    if source.resolve() == output.resolve():
        raise ValueError("Report must not overwrite the source draft")
    report = review_draft(json.loads(source.read_text(encoding="utf-8-sig")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output, report
