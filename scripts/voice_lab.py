"""Quarantined local auditions; human admission is separate from synthesis.

Run from repository root with .venv/Scripts/python.exe scripts/voice_lab.py audition
or review VOICE_ID --reviewer NAME --confirm-listened --confirm-dissimilar.
No model is trained by this script. Never synthesizes blacklisted voices.
"""

import argparse
import hashlib
import json

from studio.core.config import get_settings
from studio.core.voice_audition import DEFAULT_TEXT as TEXT
from studio.core.voice_audition import audition_sample
from studio.core.voice_policy import assert_not_blocked, signature
from studio.voices import load_registry


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audition", "review"])
    parser.add_argument("voice", nargs="?")
    parser.add_argument("--reviewer", default="")
    for flag in ["confirm-listened", "confirm-dissimilar", "confirm-pronunciation", "confirm-natural", "confirm-clean"]:
        parser.add_argument("--" + flag, action="store_true")
    args = parser.parse_args()
    reg = load_registry(get_settings())
    ids = [args.voice] if args.voice else [reg.default_for("vi").id]
    if args.action == "review" and not args.voice:
        parser.error("Specify one voice to review")
    for vid in ids:
        profile = reg.get(vid)
        assert_not_blocked(profile.provider, profile.id, profile.params)
        folder = reg.root / "candidates" / vid
        folder.mkdir(parents=True, exist_ok=True)
        sample = folder / "audition.wav"
        meta = folder / "audition.json"
        if args.action == "audition":
            print(str(audition_sample(reg, profile, TEXT).resolve()), flush=True)
        else:
            if not all(
                [
                    args.reviewer.strip(),
                    args.confirm_listened,
                    args.confirm_dissimilar,
                    args.confirm_pronunciation,
                    args.confirm_natural,
                    args.confirm_clean,
                ]
            ):
                parser.error("Listen first, then explicitly confirm all five listening checks and name reviewer")
            data = json.loads(meta.read_text(encoding="utf-8"))
            if data["voice_signature"] != signature(profile) or data["sha256"] != sha(sample):
                parser.error("Audition changed; generate and review the current sample")
            out = reg.root / "reviews" / (vid + ".json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(
                    {
                        "status": "APPROVED",
                        "reviewer": args.reviewer,
                        "voice_signature": signature(profile),
                        "test_audio_path": str(sample.resolve()),
                        "test_audio_sha256": sha(sample),
                        "checks": {
                            k: True
                            for k in [
                                "intelligible",
                                "natural",
                                "pronunciation",
                                "not_similar_to_maianh",
                                "no_artifacts",
                            ]
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(str(out.resolve()))


if __name__ == "__main__":
    main()
