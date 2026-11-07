"""VieNeu-TTS worker process - runs with the VieNeu venv's python, never imported by studio.

    <vieneu venv>/python -I vieneu_runner.py

Loads the model once, then reads one JSON request per stdin line:
    {"text": "...", "voice": "Thái Sơn", "out": "C:/.../s01.wav", "temperature": 0.7, "seed": 123}
and answers one JSON line on stdout: {"ok": true, "sec": 4.2} or {"ok": false, "error": "..."}.
Everything the libraries print goes to stderr, so stdout carries only the protocol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from importlib.metadata import version
from pathlib import Path


def _blocked(name):
    normalized = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", name).lower())
    return not normalized or any(token in normalized for token in ("maianh", "quangson"))


def main() -> int:
    proto = sys.stdout
    sys.stdout = sys.stderr  # keep library prints off the protocol channel
    proto.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--binding", default="{}")
        binding = json.loads(parser.parse_args().binding)
        if binding.get("package_version") and version("vieneu") != binding["package_version"]:
            raise ValueError("VieNeu package version changed; re-evaluate the voice")
        import torch
        import vieneu
        from vieneu import Vieneu

        t0 = time.time()
        model_args = {}
        if binding.get("revision"):
            from huggingface_hub import snapshot_download

            model_args["backbone_repo"] = snapshot_download(
                binding["model"], revision=binding["revision"], local_files_only=True
            )
            model_args["model_subfolder"] = binding.get("model_subfolder", "update")
        tts = Vieneu(**model_args)
        presets = json.loads(
            (Path(vieneu.__file__).parent / "assets/voices_v3_turbo.json").read_text(encoding="utf-8")
        )["presets"]
        rate = int(getattr(tts, "sample_rate", 48000))
        banned_codes = [spec["codes"] for name, spec in presets.items() if _blocked(name) and spec.get("codes")]
        voices = [
            v for _, v in tts.list_preset_voices()
            if not _blocked(v)
            and not any(_blocked(alias) for alias in presets.get(v, {}).get("aliases", []))
            and not any(presets.get(v, {}).get("codes") == codes for codes in banned_codes)
        ]
    except Exception as e:  # noqa: BLE001 - reported to the caller, which falls back to another voice
        proto.write(json.dumps({"ok": False, "error": f"load failed: {type(e).__name__}: {e}"}) + "\n")
        proto.flush()
        return 1
    ready = {
        "ok": True,
        "ready": True,
        "load_sec": round(time.time() - t0, 1),
        "cuda": torch.cuda.is_available(),
        "voices": voices,
    }
    proto.write(json.dumps(ready, ensure_ascii=False) + "\n")
    proto.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req.get("voice") not in voices:
                raise ValueError("Unknown, unspecified or blacklisted VieNeu voice")
            if req.get("preset_sha256"):
                actual = hashlib.sha256(
                    json.dumps(presets[req["voice"]], sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                if actual != req["preset_sha256"]:
                    raise ValueError("Voice preset changed; audition and review again")
            torch.manual_seed(int(req.get("seed", 0)))
            audio = tts.infer(
                req["text"], voice=req.get("voice"), temperature=float(req.get("temperature", 0.7)), batch_size=1
            )
            tts.save(audio, req["out"])
            resp = {"ok": True, "sec": round(len(audio) / rate, 3)}
        except Exception as e:  # noqa: BLE001
            resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        proto.write(json.dumps(resp, ensure_ascii=False) + "\n")
        proto.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
