import json
import wave

import numpy as np
import pytest

from studio.core.subtitles import Word
from studio.social_video import voice_repair as vr

from .conftest import needs_ffmpeg


def fixture_voice(monkeypatch):
    monkeypatch.setattr(vr, "assert_social_config", lambda cfg: None)
    monkeypatch.setattr(vr, "social_profile", lambda cfg: (None, None))
    monkeypatch.setattr(vr, "signature", lambda profile: "admitted-voice")


@needs_ffmpeg
@pytest.mark.parametrize("asr_onset", [900, 1200])
def test_context_is_cut_at_a_safe_gap_and_final_audio_keeps_pitch(tmp_path, monkeypatch, asr_onset):
    fixture_voice(monkeypatch)

    def generate(text, out, cfg):
        assert text == "Tôi kể lại chuyện này. Nhà tôi đó." and cfg["speed"] == 1.0
        t = np.arange(96000) / 48000
        pcm = np.zeros(96000)
        pcm[:43200] = np.sin(2 * np.pi * 330 * t[:43200]) * 5000
        pcm[57600:91200] = np.sin(2 * np.pi * 440 * t[57600:91200]) * 5000
        with wave.open(str(out), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(pcm.astype("<i2").tobytes())

    def recognize(path, *args, **kwargs):
        if path.name.endswith(".source.wav"):
            return [
                Word("Tôi", 0, 200),
                Word("kể", 200, 400),
                Word("lại", 400, 600),
                Word("chuyện", 600, 800),
                Word("này.", 800, 900),
                Word("Nhà", asr_onset, 1500),
                Word("tôi", 1500, 1700),
                Word("đó.", 1700, 1900),
            ]
        return [Word("Nhà", 100, 300), Word("tôi", 300, 500), Word("đó.", 500, 700)]

    monkeypatch.setattr(vr, "generate", generate)
    monkeypatch.setattr(vr, "faster_whisper_words", recognize)
    out, words, evidence = vr.repair_clip("Nhà tôi đó.", {"speed": 1.25}, tmp_path)
    assert 1.04 < evidence["crop_start_seconds"] < 1.08 and evidence["creator_approved"] is False
    assert evidence["pcm_quiet_gap"]["end"] == pytest.approx(1.2, abs=.001)
    with wave.open(str(out), "rb") as stream:
        audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").reshape(-1, 2).mean(1)
    f = np.fft.rfftfreq(len(audio), 1 / 48000)
    peak = f[np.argmax(np.abs(np.fft.rfft(audio)))]
    assert abs(peak - 440) < 10  # The temporary 330 Hz context is absent, speech pitch stays intact.


def test_failed_repairs_are_bounded_and_never_approved(tmp_path, monkeypatch):
    fixture_voice(monkeypatch)
    calls = []
    monkeypatch.setattr(vr, "generate", lambda text, out, cfg: (calls.append(text), out.write_bytes(b"raw")))
    monkeypatch.setattr(vr, "faster_whisper_words", lambda *a, **k: [Word("Sai", 100, 500)])
    with pytest.raises(ValueError, match="Bounded"):
        vr.repair_clip("Nhà tôi đó.", {"speed": 1.25}, tmp_path, max_attempts=10)
    assert len(calls) == 2
    assert json.loads((tmp_path / "repair_evidence.json").read_text())["creator_approved"] is False


def test_duplicate_take_cannot_leak_into_approved_sentence():
    words = [Word(t, i * 100, i * 100 + 80) for i, t in enumerate("Nhà tôi đó. Nhà tôi đó.".split())]
    with pytest.raises(ValueError, match="extra speech"):
        vr.validate("Nhà tôi đó.", words, 2)


def test_pronunciation_punctuation_cannot_rewrite_approved_words(tmp_path, monkeypatch):
    fixture_voice(monkeypatch)
    with pytest.raises(ValueError, match="approved words"):
        vr.repair_clip("Nhà tôi đó.", {"speed": 1.25}, tmp_path, spoken_text="Nhà bà đó.")
