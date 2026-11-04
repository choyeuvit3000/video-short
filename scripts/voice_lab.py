"""Quarantined local auditions; human admission is separate from synthesis.

Run from repository root with .venv/Scripts/python.exe scripts/voice_lab.py audition
or review VOICE_ID --reviewer NAME --confirm-listened --confirm-dissimilar.
No model is trained by this script. Never synthesizes blacklisted voices.
"""

import argparse
import hashlib
import json

from studio.core.config import get_settings
from studio.core.voice_policy import assert_not_blocked, signature
from studio.providers.tts.vieneu import VieneuTTS
from studio.voices import load_registry

TEXT = (
    "Chào buổi sáng, hôm nay mình cùng xem nhanh một bài trên Threads. "
    "Giữ đúng ý người đăng, đọc rõ từng câu và nghỉ một chút ở dấu chấm. "
    "Chiếc ví thì muốn nghỉ ngơi, còn công nghệ lại ra mắt mỗi ngày. "
    "Một trăm hai mươi nghìn đồng, ngày ba mươi mốt tháng mười."
)
CANDIDATES = ["vieneu-vi-thaison", "vieneu-vi-ductri", "vieneu-vi-minhtriet"]


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
    provider = VieneuTTS(reg)
    ids = [args.voice] if args.voice else CANDIDATES
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
            old = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
            if not (
                sample.is_file()
                and old.get("voice_signature") == signature(profile)
                and old.get("text") == TEXT
                and old.get("sha256") == sha(sample)
            ):
                provider.audition(TEXT, profile, sample)
            meta.write_text(
                json.dumps(
                    {
                        "status": "QUARANTINED",
                        "voice_signature": signature(profile),
                        "text": TEXT,
                        "sha256": sha(sample),
                        "preference": "deep male Southern Vietnamese",
                        "training": "not started",
                        "human_listening": "required",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(str(sample.resolve()), flush=True)
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
