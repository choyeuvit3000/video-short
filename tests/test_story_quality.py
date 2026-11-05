"""Regression contracts for the creator's onset, compact-card and horror-mix feedback."""

import json
import random
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import ImageFont

from studio.core.audio_boundaries import protect_pcm
from studio.core.errors import ManualGateRequired
from studio.core.subtitles import Word, save_words
from studio.social_video import bgclips, story_cards, story_policy, story_sound
from studio.social_video.quality import sha256
from studio.social_video.reddit_edit import partition
from studio.social_video.util import write_json

from .conftest import needs_ffmpeg


def pcm(path, samples, rate=48000):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(np.asarray(samples).shape[1] if np.asarray(samples).ndim == 2 else 1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return path


def samples(path):
    with wave.open(str(path), "rb") as stream:
        return np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")


def test_padding_preserves_even_very_quiet_onsets_and_is_idempotent(tmp_path):
    original = np.concatenate([np.full(900, 35), np.full(4800, 2000), np.full(700, 28)]).astype("<i2")
    src = pcm(tmp_path / "raw.wav", original)
    out = tmp_path / "safe.wav"
    report = protect_pcm(src, out)
    result = samples(out)
    start = np.flatnonzero(result)[0]
    np.testing.assert_array_equal(result[start : start + len(original)], original)
    assert report["samples_removed"] == 0
    before = out.read_bytes()
    protect_pcm(out, out)
    assert before == out.read_bytes()


def test_sentence_boundary_has_225_ms_minimum_without_cutting_breaths(tmp_path):
    src = pcm(tmp_path / "raw.wav", np.full(4800, 2000))
    dst = tmp_path / "safe.wav"
    protect_pcm(src, dst)
    data = samples(dst)
    active = np.flatnonzero(data)
    assert active[0] == 4800
    assert len(data) - active[-1] - 1 == 6000
    assert (active[0] + len(data) - active[-1] - 1) / 48000 == 0.225
    silent = pcm(tmp_path / "silent.wav", np.zeros(4800))
    with pytest.raises(ValueError, match="silence"):
        protect_pcm(silent, dst)


def test_content_first_keeps_complete_two_minute_story():
    groups = [[f"Đoạn đầy đủ {i}."] for i in range(4)]
    assert len(partition(groups, [(None, 30)] * 4)) == 1


def test_long_story_prefers_explicit_suspense_break_and_retains_every_sentence():
    texts = [f"Đoạn chuyện thứ {i}." for i in range(8)]
    vi = {"paragraphs": texts, "suspense_breaks": [2]}
    parts = partition([[s] for s in texts], [(None, 25)] * 8, vi=vi)
    assert len(parts[0]) == 3  # reviewed 75 s cliffhanger, rather than arbitrary timer
    assert [k for part in parts for g, k in part] == list(range(8))


def test_closing_question_is_local_editable_and_not_duplicated():
    vi = {"paragraphs": ["Tôi nghe tiếng ru ngoài cửa."]}
    story_policy.editorial_defaults(vi)
    question = vi["closing_question"]
    story_policy.editorial_defaults(vi)
    assert len(vi["paragraphs"]) == 2 and "giả giọng" in question
    manual = {"paragraphs": ["Chuyện kể. Bạn nghĩ sao?"], "closing_question": "Bạn nghĩ sao?"}
    assert len(story_policy.editorial_defaults(manual)["paragraphs"]) == 1
    assert story_policy.editorial_defaults({"paragraphs": ["Kết."], "closing_question": False})["paragraphs"] == [
        "Kết."
    ]


def test_compact_pages_keep_all_words_with_no_more_than_three_lines():
    texts = ("Tôi nghe một tiếng cười rất gần trong căn nhà bỏ hoang. " * 10).split()
    font = ImageFont.truetype(story_cards.FONT, 56)
    pages = story_cards.layout(texts, font)
    assert all(len(page) <= 3 for page in pages)
    assert [i for page in pages for line in page for i in line] == list(range(len(texts)))
    assert 0.15 <= story_cards.Y / story_cards.H <= 0.18


def test_phrase_highlight_follows_actual_anchors_and_keeps_page_geometry(tmp_path, monkeypatch):
    texts = "Một người vừa đứng sau lưng tôi.".split()
    words = [Word(t, 100 + i * 220, 260 + i * 220) for i, t in enumerate(texts)]
    seen = []
    from PIL import Image

    def draw(story, text, lines, active):
        seen.append((lines, active))
        return Image.new("RGBA", (2, 2))

    monkeypatch.setattr(story_cards, "draw_card", draw)
    frames = story_cards.timed_cards({}, words, 2, tmp_path, "fixture")
    assert sum(share for path, share in frames) == pytest.approx(1)
    assert frames[0][1] * 2 == pytest.approx(words[3].start_ms / 1000)
    assert seen[0][0] == seen[1][0] and max(len(active) for lines, active in seen) <= 3


def test_horror_random_never_falls_back_to_legacy_minecart(tmp_path, monkeypatch):
    monkeypatch.setattr(bgclips, "ASSETS", tmp_path)
    (tmp_path / "minecraft_old.mp4").write_bytes(b"old lava")
    with pytest.raises(ValueError, match="reviewed"):
        bgclips.pick(60, random.Random(1), family="horror")


def test_horror_pool_checks_actual_fps_and_file_integrity(tmp_path, monkeypatch):
    clip = tmp_path / "night.mp4"
    clip.write_bytes(b"fixture")
    write_json(
        tmp_path / "horror_backgrounds.json", {"clips": [{"file": clip.name, "accepted": True, "sha256": sha256(clip)}]}
    )
    monkeypatch.setattr(bgclips, "ASSETS", tmp_path)
    monkeypatch.setattr(
        bgclips,
        "run",
        lambda args: SimpleNamespace(
            stdout=json.dumps({"streams": [{"width": 1080, "height": 1920, "r_frame_rate": "30/1"}]})
        ),
    )
    assert bgclips.horror_pool() == []  # metadata cannot pretend 30 fps is 60
    clip.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        bgclips.horror_pool()


def sound_fixture(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    (assets / "horror_sfx").mkdir(parents=True)
    tone = np.sin(np.arange(48000 * 2) / 20) * 4000
    voice = pcm(tmp_path / "voice.wav", np.column_stack((tone, tone)))
    music = pcm(tmp_path / "music.wav", np.sin(np.arange(48000 * 4) / 70) * 3000)
    for name in story_sound.SFX.values():
        pcm(assets / "horror_sfx" / name, np.sin(np.arange(48000) / 12) * 2000)
    wp = tmp_path / "words.json"
    texts = "Tôi nghe tiếng cười phía sau.".split()
    save_words(wp, [Word(t, i * 200 + 100, i * 200 + 270) for i, t in enumerate(texts)], source="manual")
    write_json(tmp_path / "vi.json", {"paragraphs": [" ".join(texts)]})
    write_json(
        tmp_path / "voice_manifest.json",
        {"body": [{"path": str(voice), "seconds": 2}], "hooks": [None], "timing_files": [str(wp)]},
    )
    write_json(tmp_path / "part_plan.json", {"parts": [{"part": 1, "sentences": [0]}]})
    monkeypatch.setattr(story_sound, "ASSETS", assets)
    monkeypatch.setattr(story_sound.horrormusic, "ensure", lambda count: [music])
    return voice


def test_sound_plan_cues_are_bound_to_spoken_word_and_sensitive_story_has_no_sfx(tmp_path, monkeypatch):
    sound_fixture(tmp_path, monkeypatch)
    cfg = {"reddit": {}}
    plan = story_sound.prepare_plan(tmp_path, cfg)
    part = plan["parts"]["1"]
    laugh = next(x for x in part["events"] if x["kind"] == "laugh")
    assert laugh["at"] == 0.7 and part["relative_music_db"] == -23
    write_json(tmp_path / "vi.json", {"paragraphs": ["Tôi nghe tiếng cười phía sau."], "sensitive": True})
    assert story_sound.prepare_plan(tmp_path, cfg)["parts"]["1"]["events"] == []


@needs_ffmpeg
def test_real_mix_has_audible_bed_preserves_voice_and_rejects_changed_asset(tmp_path, monkeypatch):
    voice = sound_fixture(tmp_path, monkeypatch)
    plan = story_sound.prepare_plan(tmp_path, {"reddit": {}})
    plan["parts"]["1"]["events"] = []  # isolate the music layer from SFX and narration
    write_json(tmp_path / "sound_plan.json", plan)
    out = tmp_path / "mix.wav"
    story_sound.mix(tmp_path, 1, voice, out, 2)
    report = json.loads((tmp_path / "1_mix_report.json").read_text())
    assert report["music_relative_db_before_duck"] == -23 and report["voice_preserved_at_unity"]
    assert report["dry_voice_only"] is False and report["output_sha256"] == sha256(out)
    mixed_left = samples(out).reshape(-1, 2)[:, 0].astype(float)
    original = samples(voice).reshape(-1, 2)[:, 0].astype(float)
    residual = mixed_left - original
    ratio = np.sqrt(np.mean(residual**2)) / np.sqrt(np.mean(original**2))
    assert 0.001 < ratio < 0.1  # a real quiet bed, not just an asserted report field
    Path(plan["assets"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(ManualGateRequired):
        story_sound.mix(tmp_path, 1, voice, out, 2)


@needs_ffmpeg
def test_native_pcm_cache_reuses_valid_audio_and_regenerates_corruption(tmp_path, monkeypatch):
    from studio.core import voice_policy
    from studio.social_video import local_voice, tts

    calls, policy_checks = [], []
    monkeypatch.setattr(voice_policy, "assert_social_config", lambda cfg: policy_checks.append(True))
    monkeypatch.setattr(voice_policy, "social_profile", lambda cfg: (None, None))
    monkeypatch.setattr(voice_policy, "signature", lambda profile: "pinned-test-voice")
    monkeypatch.setattr(tts, "TTS_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tts, "role_cfg", lambda cfg, role: cfg)

    def generate(text, output, cfg):
        calls.append(text)
        pcm(output, np.sin(np.arange(24000) / 20) * 4000)

    monkeypatch.setattr(local_voice, "generate", generate)
    monkeypatch.setattr(tts, "synth", lambda *a: pytest.fail("Native narration must not round-trip MP3"))
    cfg = {"engines": ["vieneu"], "vieneu": {"speed": 1.25}}
    first = tts.voice_sentences(["Nhà tôi ở miền Tây."], tmp_path / "work1", cfg)[0][0]
    second = tts.voice_sentences(["Nhà tôi ở miền Tây."], tmp_path / "work2", cfg)[0][0]
    assert len(calls) == 1 and first.read_bytes() == second.read_bytes()
    next((tmp_path / "cache/pcm").glob("*.wav")).write_bytes(b"corrupt")
    tts.voice_sentences(["Nhà tôi ở miền Tây."], tmp_path / "work3", cfg)
    assert len(calls) == 2 and len(policy_checks) == 3


def test_asr_cache_binds_audio_text_model_and_raw_timestamps(tmp_path, monkeypatch):
    from studio.providers import align
    from studio.social_video.review_voice import align_clip

    calls = []
    audio = pcm(tmp_path / "voice.wav", np.full(4800, 2000))

    def recognize(*args, **kw):
        calls.append(True)
        return [Word("Nhà", 100, 300), Word("tôi.", 300, 500)]

    monkeypatch.setattr(align, "faster_whisper_words", recognize)
    cfg = {"reddit": {"word_timing_model": "test-model"}}
    align_clip(tmp_path, "line", audio, 1, "Nhà tôi.", cfg)
    align_clip(tmp_path, "line", audio, 1, "Nhà tôi.", cfg)
    assert len(calls) == 1
    audio.write_bytes(audio.read_bytes() + b"changed")
    align_clip(tmp_path, "line", audio, 1, "Nhà tôi.", cfg)
    assert len(calls) == 2


def test_missing_onset_cannot_be_hidden_by_overall_high_asr_match(tmp_path, monkeypatch):
    from studio.providers import align
    from studio.social_video.review_voice import align_clip

    text = "Nhà tôi ở một xóm vắng miền Tây và chúng tôi thường chơi cùng nhau khi trời vừa tối."
    rec = [Word(t, 100 + i * 100, 180 + i * 100) for i, t in enumerate(text.split()[1:])]
    audio = pcm(tmp_path / "voice.wav", np.full(4800, 2000))
    monkeypatch.setattr(align, "faster_whisper_words", lambda *a, **k: rec)
    with pytest.raises(ManualGateRequired):
        align_clip(tmp_path, "line", audio, 3, text, {"reddit": {}})
    audit = json.loads((tmp_path / "work/speech_checks/line.json").read_text(encoding="utf-8"))
    assert audit["onset"]["matched"] is False


def test_optional_scene_is_pinned_for_preview_and_rejects_changed_photo(tmp_path, monkeypatch):
    from PIL import Image

    from studio.social_video import images, story_scenes

    photo = tmp_path / "scene.png"
    Image.new("RGB", (100, 100), "blue").save(photo)
    monkeypatch.setattr(images, "find", lambda *a: photo)
    story_scenes.prepare(tmp_path, {"scenes": {"0": "old house"}})
    assert story_scenes.photo(tmp_path, 2) == photo
    photo.write_bytes(b"changed")
    with pytest.raises(ManualGateRequired):
        story_scenes.photo(tmp_path, 2)
