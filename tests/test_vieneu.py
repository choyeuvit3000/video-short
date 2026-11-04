"""VieNeu provider protocol, with a fake runner (the real model lives in its own GPU venv)."""

import sys

import pytest

from studio.core.errors import ProviderUnavailable
from studio.core.media_probe import probe
from studio.providers.tts import vieneu
from studio.voices import load_registry

from .conftest import needs_ffmpeg

FAKE_RUNNER = r'''
import json, math, struct, sys, wave
print(json.dumps({"ok": True, "ready": True, "voices": ["Mai Anh"], "cuda": False}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req["voice"] != "Mai Anh":
        print(json.dumps({"ok": False, "error": "unknown voice"}), flush=True)
        continue
    with wave.open(req["out"], "wb") as w:  # a 1 s tone stands in for the voice
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(48000)))
    print(json.dumps({"ok": True, "sec": 1.0, "seed": req["seed"]}), flush=True)
'''


@pytest.fixture
def fake_vieneu(tmp_path, monkeypatch):
    runner = tmp_path / "fake_runner.py"
    runner.write_text(FAKE_RUNNER, encoding="utf-8")
    monkeypatch.setattr(vieneu, "RUNNER", runner)
    monkeypatch.setenv("STUDIO_VIENEU_PYTHON", sys.executable)
    vieneu._close_all()
    vieneu._runners.clear()
    yield
    vieneu._close_all()
    vieneu._runners.clear()


def test_vieneu_profiles_are_commercial_and_fall_back(settings):
    reg = load_registry(settings)
    voices = [p for p in reg.profiles.values() if p.provider == "vieneu"]
    assert len(voices) >= 3 and all(p.status == "ready" and p.location == "node:home-gpu" for p in voices)
    assert all("Apache-2.0" in p.license and p.fallback in reg.profiles for p in voices)
    assert reg.default_for("vi").provider != "vieneu"  # machine defaults never leak into tests


def test_vieneu_missing_venv(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VIENEU_PYTHON", str(tmp_path / "nope" / "python.exe"))
    reg = load_registry(settings)
    prov = vieneu.VieneuTTS(reg)
    assert "install_vieneu.ps1" in prov.check(reg.get("vieneu-vi-maianh"))


@needs_ffmpeg
def test_vieneu_runner_protocol_and_speed(settings, fake_vieneu, tmp_path):
    from studio.voices import with_speed

    reg = load_registry(settings)
    prov = vieneu.VieneuTTS(reg)
    prof = reg.get("vieneu-vi-maianh")
    res = prov.synthesize("Xin chào.", prof, tmp_path / "a.wav")
    assert res.words is None and abs(probe(res.audio_path).duration - 1.0) < 0.05
    fast = prov.synthesize("Xin chào.", with_speed(prof, 1.25), tmp_path / "b.wav")  # atempo, same process
    assert abs(probe(fast.audio_path).duration - 0.8) < 0.05
    # A sample-rate trick would also shorten the clip, but raise this tone by 25%. Verify actual pitch.
    import wave

    import numpy as np

    def dominant_frequency(path):
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float)
        samples = samples[len(samples) // 4:3 * len(samples) // 4]
        spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
        return rate, np.fft.rfftfreq(len(samples), 1 / rate)[spectrum.argmax()]

    base_rate, base_pitch = dominant_frequency(res.audio_path)
    fast_rate, fast_pitch = dominant_frequency(fast.audio_path)
    assert base_rate == fast_rate == 48000
    assert abs(fast_pitch - base_pitch) < 4  # FFT resolution tolerance, Hz
    assert len(vieneu._runners) == 1
    from dataclasses import replace

    with pytest.raises(ProviderUnavailable, match="unknown voice"):
        prov.synthesize("x", replace(prof, params={"voice": "Không có"}), tmp_path / "c.wav")
