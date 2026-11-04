"""Isolated OmniVoice JSON-lines worker. No Studio imports or production admission bypass."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    proto = sys.stdout
    proto.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout = sys.stderr

    def send(data):
        proto.write(json.dumps(data, ensure_ascii=False) + "\n")
        proto.flush()

    try:
        import numpy as np
        import soundfile as sf
        import torch
        from huggingface_hub import snapshot_download
        from omnivoice import OmniVoice

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for this OmniVoice profile")
        path = snapshot_download(args.model, revision=args.revision)
        model = OmniVoice.from_pretrained(path, device_map="cuda:0", dtype=torch.float16, attn_implementation="sdpa")
        prompts = {}
        send({"ok": True, "cuda": True, "revision": args.revision})
    except Exception as exc:
        send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            name = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", req.get("voice", "")).lower())
            if not name or "maianh" in name or name.startswith(("edge", "microsoftedge")):
                raise ValueError("Blacklisted or missing voice identity")
            ref = Path(req["ref_audio"])
            ref_name = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(ref)).lower())
            if "maianh" in ref_name:
                raise ValueError("Mai Anh cannot be used as a cloning reference")
            digest = hashlib.sha256(ref.read_bytes()).hexdigest()
            if digest != req["ref_sha256"]:
                raise ValueError("Reference audio changed")
            key = (digest, req["ref_text"])
            if key not in prompts:
                prompts[key] = model.create_voice_clone_prompt(ref_audio=str(ref), ref_text=req["ref_text"])
            torch.manual_seed(int(req["seed"]))
            audio = model.generate(
                text=req["text"],
                language=req["language"],
                voice_clone_prompt=prompts[key],
                speed=float(req["speed"]),
                num_step=int(req["num_step"]),
            )[0]
            if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 1e-5:
                raise ValueError("Empty, nonfinite or silent output")
            out = Path(req["out"])
            tmp = out.with_name(out.stem + ".partial.wav")
            sf.write(str(tmp), audio, model.sampling_rate, subtype="PCM_16")
            tmp.replace(out)
            send({"ok": True, "seconds": len(audio) / model.sampling_rate, "sample_rate": model.sampling_rate})
        except Exception as exc:
            import traceback

            traceback.print_exc()
            send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
