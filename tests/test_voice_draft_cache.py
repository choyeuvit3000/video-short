from pathlib import Path

from studio.core.speech_checks import file_sha
from studio.core.subtitles import Word
from studio.social_video import review_voice as rv
from studio.social_video.util import write_json
from studio.social_video.voice_repair import record_recognition


def test_draft_cache_checks_all_audio_hashes_and_does_not_approve(tmp_path, monkeypatch):
    import studio.social_video.util as util

    monkeypatch.setattr(rv, "social_profile", lambda cfg: (None, None))
    monkeypatch.setattr(rv, "signature", lambda profile: "same-voice")
    monkeypatch.setattr(util, "media_duration", lambda path: 2.0)
    cfg = {"tts": {"engines": ["vieneu"]}, "reddit": {"narration_speed": 1.25}}
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"original")
    rv.cache_draft_voice(tmp_path, ["Lời đọc."], [(audio, 2.0)], cfg)
    assert rv.cached_draft_voice(tmp_path, ["Lời đọc."], cfg) == [(audio, 2.0)]
    assert rv.cached_draft_voice(tmp_path, ["Đã sửa."], cfg) is None
    audio.write_bytes(b"tampered")
    assert rv.cached_draft_voice(tmp_path, ["Lời đọc."], cfg) is None
    assert not (tmp_path / "user_reviews.json").exists()


def test_context_asr_cache_is_recomputed_if_parent_proof_changes(tmp_path, monkeypatch):
    import studio.providers.align as align

    audio, parent = tmp_path / "speech.wav", tmp_path / "context.wav"
    audio.write_bytes(b"spoken")
    parent.write_bytes(b"original")
    words = [Word("Nhà", 100, 300), Word("tôi.", 350, 600)]
    record_recognition(tmp_path, "test", audio, "Nhà tôi.", "large-v3-turbo", words, provenance=[parent])
    calls = []
    monkeypatch.setattr(align, "faster_whisper_words", lambda *a, **k: (calls.append(k), words)[1])
    cfg = {"reddit": {"word_timing_model": "large-v3-turbo"}}
    path = Path(rv.align_clip(tmp_path, "test", audio, 1.0, "Nhà tôi.", cfg))
    assert path.is_file() and not calls
    parent.write_bytes(b"changed")
    rv.align_clip(tmp_path, "test", audio, 1.0, "Nhà tôi.", cfg)
    assert len(calls) == 1


def test_series_timing_uses_measured_words_and_preserves_pending_listening(tmp_path):
    from studio.core.subtitles import save_words
    from studio.social_video.series_timing import audit

    audio, timing = tmp_path / "speech.wav", tmp_path / "speech.words.json"
    audio.write_bytes(b"spoken")
    text = "Tay lạnh. Tôi sợ."
    save_words(timing, [Word(t, i * 200, i * 200 + 150) for i, t in enumerate(text.split())], source="faster_whisper")
    write_json(
        tmp_path / "vi.json",
        {
            "paragraphs": [text],
            "episode_sentence_ranges": [[0, 1]],
            "episode_titles": ["Mẫu"],
            "episode_editorial": [{"sensory_anchor": "Tay lạnh"}],
        },
    )
    write_json(
        tmp_path / "voice_manifest.json",
        {
            "timing_files": [str(timing)],
            "body": [{"path": str(audio), "seconds": 1.0}],
        },
    )
    report = audit(tmp_path)
    assert report["episodes"][0]["hook_end_seconds"] == 0.35
    assert report["episodes"][0]["fingerprints"][0]["audio_sha256"] == file_sha(audio)
    assert report["creator_approved"] is False
