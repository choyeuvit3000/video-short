import wave

import numpy as np
import pytest

from studio.core.errors import ManualGateRequired, ProviderUnavailable
from studio.core.speech_checks import file_sha
from studio.core.subtitles import Word, save_words
from studio.core.user_review import digest
from studio.social_video import continuous_voice as cv
from studio.social_video.util import write_json


def source(tmp_path, text):
    pcm = (np.sin(np.arange(96000) / 31) * 3000).astype("<i2")
    audio = tmp_path / "source.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(pcm.tobytes())
    tokens = text.split()
    words = [
        Word(t, 100 + round(i * 1600 / len(tokens)), 100 + round((i + 1) * 1600 / len(tokens)))
        for i, t in enumerate(tokens)
    ]
    raw = tmp_path / "raw.words.json"
    save_words(raw, words, source="faster_whisper")
    return audio, raw, words, pcm


def test_sentence_partition_reconstructs_every_pcm_sample_without_extra_pauses(tmp_path):
    text = "Nhà tôi đó. Cửa vẫn mở."
    audio, raw, words, pcm = source(tmp_path, text)
    body, timing, _, report = cv.split_source(
        tmp_path, audio, raw, words, ["Nhà tôi đó.", "Cửa vẫn mở."], 0, "large-v3", tmp_path / "parts"
    )
    clips = []
    for item in body:
        with wave.open(item["path"], "rb") as stream:
            clips.append(np.frombuffer(stream.readframes(stream.getnframes()), "<i2").reshape(-1, 2))
    result = np.concatenate(clips)
    np.testing.assert_array_equal(result[:, 0], pcm)
    np.testing.assert_array_equal(result[:, 1], pcm)
    assert len(timing) == 2 and report["samples_removed"] == report["samples_inserted"] == 0
    assert report["tempo_applied_here"] is False and report["human_listening"] is False


def test_tone_ambiguity_is_reported_rather_than_claimed_to_be_correct(tmp_path):
    text = "Má nhận ra tôi đang đứng cạnh chiếc đò dưới sông."
    audio, raw, words, _ = source(tmp_path, text)
    words[0].text = "Mã"
    _, _, _, report = cv.split_source(tmp_path, audio, raw, words, [text], 0, "large-v3", tmp_path / "parts")
    assert report["onset"]["literal_match"] is False
    assert report["onset"]["tone_ambiguity_requires_final_listening"] is True
    assert report["word_disagreements"][0] == {"expected": ["má"], "raw": ["mã"]}


def test_missing_onset_and_numeric_marker_still_stop_preparation(tmp_path):
    text = "Khách đi đò của tôi đã chết hai mươi sáu năm."
    audio, raw, words, _ = source(tmp_path, text)
    words[0].text = "Thắt"
    with pytest.raises(ManualGateRequired):
        cv.split_source(tmp_path, audio, raw, words, [text], 0, "large-v3", tmp_path / "parts")
    text = "Có năm phẩy hai người ở đó."
    audio, raw, words, _ = source(tmp_path, "Có năm hai người ở đó.")
    with pytest.raises(ProviderUnavailable, match="phẩy"):
        cv.split_source(tmp_path, audio, raw, words, [text], 0, "large-v3", tmp_path / "parts")


def test_continuous_cache_checks_the_original_source_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "social_profile", lambda cfg: (None, None))
    monkeypatch.setattr(cv, "signature", lambda profile: "voice")
    source_file = tmp_path / "source.wav"
    source_file.write_bytes(b"actual")
    cfg = {"tts": {}, "reddit": {"narration_speed": 1.0}}
    write_json(
        tmp_path / "continuous_voice.json",
        {
            "texts": digest(["Nội dung."]),
            "voice_signature": "voice",
            "choices": digest({"tts": {}, "speed": 1.0}),
            "timing_files": ["actual.words.json"],
            "files": [{"path": str(source_file), "sha256": file_sha(source_file)}],
        },
    )
    assert cv.cached_timings(tmp_path, ["Nội dung."], cfg) == ["actual.words.json"]
    source_file.write_bytes(b"changed")
    with pytest.raises(ManualGateRequired):
        cv.cached_timings(tmp_path, ["Nội dung."], cfg)
