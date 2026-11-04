"""Screen existing samples only. Cosine is evidence, never a listening approval.
Run using the private VieNeu interpreter, with repository root as cwd.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from vieneu._v3_turbo_engine.speaker import OnnxSpeakerEncoder

root = Path.cwd() / "voices" / "candidates"
checkpoint = next(
    Path("D:/studio-node/hf/hub/models--pnnbao-ump--VieNeu-TTS-v3-Turbo/snapshots").glob("*/speaker_encoder.onnx")
)
encoder = OnnxSpeakerEncoder(str(checkpoint), device="cpu")
reference = Path("D:/Video-maker/nghe-thu-giong/1_vieneu-vi-maianh.mp3")
ffmpeg = Path("tools/ffmpeg/bin/ffmpeg.exe")
if not ffmpeg.is_file():
    ffmpeg = "ffmpeg"
refwav = root / "existing_reference.wav"
subprocess.run([str(ffmpeg), "-y", "-v", "error", "-i", str(reference), "-ac", "1", str(refwav)], check=True)
a, sr = sf.read(refwav)
r = encoder.embed(a, sr)
for wav in root.glob("*/audition.wav"):
    a, sr = sf.read(wav)
    a = a.mean(axis=1) if a.ndim == 2 else a
    v = encoder.embed(a, sr)
    result = {
        "method": "speaker embedding cosine; uncalibrated screening, no approval",
        "reference": "existing Mai Anh recording; never resynthesized",
        "audio_sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
        "cosine_to_maianh": float(np.dot(r, v) / (np.linalg.norm(r) * np.linalg.norm(v))),
        "duration_seconds": len(a) / sr,
        "peak": float(np.max(np.abs(a))),
        "rms": float(np.sqrt(np.mean(a * a))),
        "human_review": "REQUIRED",
    }
    wav.with_suffix(".screen.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(wav.parent.name, result["cosine_to_maianh"], flush=True)
