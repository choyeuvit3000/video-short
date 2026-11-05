"""Measure approved episode hooks and sensory cues from real speech anchors."""

import re
from pathlib import Path

from ..core.subtitles import load_words
from .quality import sha256
from .reddit import chunks
from .story_editorial import sentences
from .util import read_json, write_json


def audit(folder):
    vi = read_json(folder / "vi.json")
    manifest = read_json(folder / "voice_manifest.json")
    texts = [s for group in chunks(vi["paragraphs"]) for s in group]
    rows = []
    for i, (a, b) in enumerate(vi["episode_sentence_ranges"]):
        words, offset, fingerprints = [], 0.0, []
        for j in range(a, b):
            path = Path(manifest["timing_files"][j])
            local, origin = load_words(path)
            if origin not in ("faster_whisper", "manual"):
                raise ValueError("Measured timing requires real speech anchors")
            for word in local:
                for token in re.findall(r"\w+", word.text.casefold()):
                    words.append((token, offset + word.start_ms / 1000, offset + word.end_ms / 1000))
            clip = manifest["body"][j]
            offset += clip["seconds"]
            fingerprints.append({"audio_sha256": sha256(Path(clip["path"])), "words_sha256": sha256(path)})
        hook = sentences(texts[a])[0]
        hook_tokens = re.findall(r"\w+", hook.casefold())
        if [w[0] for w in words[: len(hook_tokens)]] != hook_tokens:
            raise ValueError("Hook words do not match the actual aligned opening")
        hook_end = words[len(hook_tokens) - 1][2]
        anchor = vi["episode_editorial"][i]["sensory_anchor"]
        needle = re.findall(r"\w+", anchor.casefold())
        found = next(
            (k for k in range(len(words) - len(needle) + 1) if [w[0] for w in words[k : k + len(needle)]] == needle),
            None,
        )
        onset = words[found][1] if found is not None else None
        rows.append(
            {
                "episode": i + 1,
                "title": vi["episode_titles"][i],
                "hook": hook,
                "hook_end_seconds": round(hook_end, 3),
                "hook_within_three_seconds": hook_end <= 3,
                "sensory_anchor": anchor,
                "sensory_start_seconds": round(onset, 3) if onset is not None else None,
                "sensory_within_fifteen_seconds": onset is not None and onset <= 15,
                "narration_seconds": round(offset, 3),
                "fingerprints": fingerprints,
            }
        )
    report = {
        "status": "AUTOMATIC_TIMING_PASS_CREATOR_LISTENING_PENDING"
        if all(r["hook_within_three_seconds"] and r["sensory_within_fifteen_seconds"] for r in rows)
        else "TIMING_REVIEW_REQUIRED",
        "creator_approved": False,
        "episodes": rows,
    }
    write_json(folder / "work/speech_checks/series_timing.json", report)
    return report
