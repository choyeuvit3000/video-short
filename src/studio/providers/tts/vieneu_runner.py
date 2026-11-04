"""VieNeu-TTS worker process - runs with the VieNeu venv's python, never imported by studio.

    <vieneu venv>/python -I vieneu_runner.py

Loads the model once, then reads one JSON request per stdin line:
    {"text": "...", "voice": "Mai Anh", "out": "C:/.../s01.wav", "temperature": 0.7, "seed": 123}
and answers one JSON line on stdout: {"ok": true, "sec": 4.2} or {"ok": false, "error": "..."}.
Everything the libraries print goes to stderr, so stdout carries only the protocol.
"""

from __future__ import annotations

import json
import sys
import time


def main() -> int:
    proto = sys.stdout
    sys.stdout = sys.stderr  # keep library prints off the protocol channel
    proto.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    try:
        import torch
        from vieneu import Vieneu

        t0 = time.time()
        tts = Vieneu()
        rate = int(getattr(tts, "sample_rate", 48000))
        voices = [v for _, v in tts.list_preset_voices()]
    except Exception as e:  # noqa: BLE001 - reported to the caller, which falls back to another voice
        proto.write(json.dumps({"ok": False, "error": f"load failed: {type(e).__name__}: {e}"}) + "\n")
        proto.flush()
        return 1
    ready = {"ok": True, "ready": True, "load_sec": round(time.time() - t0, 1),
             "cuda": torch.cuda.is_available(), "voices": voices}
    proto.write(json.dumps(ready, ensure_ascii=False) + "\n")
    proto.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req.get("voice") and req["voice"] not in voices:
                raise ValueError(f"unknown VieNeu voice {req['voice']!r}")
            torch.manual_seed(int(req.get("seed", 0)))
            audio = tts.infer(req["text"], voice=req.get("voice"),
                              temperature=float(req.get("temperature", 0.7)))
            tts.save(audio, req["out"])
            resp = {"ok": True, "sec": round(len(audio) / rate, 3)}
        except Exception as e:  # noqa: BLE001
            resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        proto.write(json.dumps(resp, ensure_ascii=False) + "\n")
        proto.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
