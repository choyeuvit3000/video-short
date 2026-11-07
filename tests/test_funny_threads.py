from pathlib import Path
from types import SimpleNamespace

import pytest

from studio.core.errors import ValidationError
from studio.core.user_review import write
from studio.social_video.funny_threads import cast_signature, cover_window, turn_frames, validate_files
from studio.voices import VoiceProfile


def registry():
    ids = {"vieneu-gallery-ngoc-huyen", "vieneu-gallery-my-duyen", "vieneu-gallery-quang-son"}
    return SimpleNamespace(
        get=lambda k: VoiceProfile(k, "vi", "local", "vieneu", params={"voice": k}) if k in ids else None
    )


def test_cover_is_three_frames_and_does_not_extend_the_timeline():
    for total in [9, 900, 901, 1799]:
        start, end = cover_window(total)
        assert end - start == 3
        assert 0 < start < end < total
        assert [start <= n < end for n in range(start - 1, end + 1)] == [False, True, True, True, False]


@pytest.mark.parametrize("total,frames", [(8, 3), (900, 4), (900, 2), (900.0, 3), (True, 3)])
def test_rejects_wrong_cover_window(total, frames):
    with pytest.raises(ValueError):
        cover_window(total, frames)


def test_turns_preserve_sentence_pause_and_image_viewing_time():
    assert turn_frames(1.3, 0.6) == 57
    assert turn_frames(0.1, 0.2) == 9  # no extra frame caused by floating point
    assert turn_frames(0.6, 0.6, 3.2) == 96
    with pytest.raises(ValueError):
        turn_frames(float("nan"), 0.6)


def test_same_author_keeps_a_voice_and_adjacent_comments_change():
    a = {
        "id": "a",
        "author": "first",
        "kind": "comment",
        "voice": "Ngọc Huyền",
        "region": "Bắc",
        "gender": "female",
        "speed": 1.15,
        "narration": "Một câu.",
    }
    b = {**a, "id": "b", "author": "second", "voice": "Mỹ Duyên", "region": "Nam"}
    assert len(cast_signature({"beats": [a, b]}, registry())["cast"]) == 2
    with pytest.raises(ValueError, match="Adjacent"):
        cast_signature({"beats": [a, {**b, "voice": "Ngọc Huyền"}]}, registry())
    with pytest.raises(ValueError, match="same author"):
        cast_signature({"beats": [a, {**b, "author": "first"}]}, registry())


def test_changed_screenshot_is_not_silently_rebound(tmp_path):
    import hashlib

    path = tmp_path / "source.png"
    path.write_bytes(b"original screenshot")
    files = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
    validate_files(files)
    path.write_bytes(b"changed screenshot")
    with pytest.raises(ValidationError, match="Changed"):
        validate_files(files)


def test_preflight_counts_comment_speech(tmp_path, monkeypatch):
    from studio import voices
    from studio.core import creative_brief

    write(tmp_path / "posts.json", [{"part_texts": ["chữ trong bài"]}])
    write(tmp_path / "merged_plan.json", {"beats": [{"narration": "bài gốc"}, {"narration": "bình luận thứ nhất"}]})
    monkeypatch.setattr(
        creative_brief,
        "prepare",
        lambda p: {
            "status": "DRAFT",
            "answers": {"voice": "voice", "speech_speed": 1.0, "pacing": "normal", "target_seconds": 45},
        },
    )
    profile = VoiceProfile("voice", "vi", "local", "mock", estimated_space_tokens_per_second=3.0)
    monkeypatch.setattr(voices, "load_registry", lambda s: SimpleNamespace(get=lambda k: profile))
    result = creative_brief.preflight(Path(tmp_path))
    assert result["scenes"] == 2
    assert result["spoken_words"] == 6


def test_unaccepted_script_cannot_start_audition(tmp_path):
    from studio.core.errors import ManualGateRequired
    from studio.social_video.funny_threads import prepare_voice

    with pytest.raises(ManualGateRequired):
        prepare_voice(tmp_path)
    assert not (tmp_path / "voice_manifest.json").exists()


def test_selected_repair_is_bound_to_words_voice_speed_and_pcm(tmp_path):
    import hashlib

    from studio.core.voice_policy import signature
    from studio.social_video.funny_threads import repair_source

    beat = {"narration": "Như này hả bà?", "speed": 1.15}
    profile = VoiceProfile("cast", "vi", "local", "vieneu", params={"voice": "Quang Sơn"})
    source = tmp_path / "checked.wav"
    source.write_bytes(b"checked take")
    repair = {
        "path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "text_sha256": hashlib.sha256(beat["narration"].encode()).hexdigest(),
        "tts_input": "Như này, hả bà?",
        "voice_signature": signature(profile),
        "speed": 1.15,
    }
    assert repair_source(beat, profile, repair) == source
    with pytest.raises(ValidationError, match="approved words"):
        repair_source(beat, profile, {**repair, "tts_input": "Nhìn này hả bà?"})
    with pytest.raises(ValidationError, match="script/voice"):
        repair_source(beat, profile, {**repair, "speed": 1.25})
    source.write_bytes(b"old rejected take restored")
    with pytest.raises(ValidationError, match="Changed"):
        repair_source(beat, profile, repair)


def test_context_asr_requires_exact_selected_pcm_and_removes_only_prefix(tmp_path, monkeypatch):
    import wave

    from studio.core.subtitles import Word
    from studio.core.user_review import read, sha
    from studio.providers import align
    from studio.social_video.funny_threads import check_speech

    context = tmp_path / "context.wav"
    selected = tmp_path / "selected.wav"
    prefix = b"\0\0" * 24000
    target = b"\1\0" * 48000
    for path, samples in [(context, prefix + target), (selected, target)]:
        with wave.open(str(path), "wb") as stream:
            stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            stream.writeframes(samples)
    write(tmp_path / "merged_plan.json", {"beats": [{"id": "comment"}]})
    write(
        tmp_path / "voice_manifest.json",
        {
            "beats": {
                "0": {
                    "audio": str(selected),
                    "source": str(selected),
                    "sha256": sha(selected),
                    "text": "Như này hả bà?",
                }
            }
        },
    )
    write(
        tmp_path / "voice_repairs.json",
        {
            "selected": {
                "comment": {
                    "full_context_audio": str(context),
                    "full_context_sha256": sha(context),
                    "crop_start_sample": 24000,
                }
            }
        },
    )
    monkeypatch.setattr(
        align,
        "faster_whisper_words",
        lambda *a, **kw: [
            Word("Lời dẫn.", 0, 400),
            Word("Như", 600, 750),
            Word("này", 750, 900),
            Word("hả", 900, 1100),
            Word("bà?", 1100, 1200),
        ],
    )
    result = check_speech(tmp_path)["0"]
    assert result["raw_transcript"] == "Như này hả bà?"
    assert result["words"][0]["start_ms"] == 100
    assert result["lossless_crop_verified"] is True
    assert result["human_listening"] == "PENDING"
    assert read(tmp_path / "voice_manifest.json")["speech_checks"]["0"]["raw_context_transcript"].startswith("Lời dẫn.")
    with wave.open(str(selected), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\2\0" * 48000)
    with pytest.raises(ValueError, match="reconstruct"):
        check_speech(tmp_path)


@pytest.mark.parametrize("inserted_frames", [3, 4])
def test_decoded_cover_detects_four_frame_regression(tmp_path, inserted_frames):
    from PIL import Image, ImageDraw

    from studio.core.ffmpeg import run_ffmpeg
    from studio.social_video.funny_threads import verify_cover

    base = Image.new("RGB", (1080, 1920), "#152b24")
    cover = base.copy()
    ImageDraw.Draw(cover).rectangle((30, 280, 1010, 620), fill="#ffdc5d")
    cover_path = tmp_path / "cover.png"
    cover.save(cover_path)
    for i in range(30):
        (cover if 15 <= i < 15 + inserted_frames else base).save(tmp_path / f"{i:02d}.png")
    result = tmp_path / "clip.mp4"
    run_ffmpeg(
        [
            "-framerate",
            "30",
            "-i",
            str(tmp_path / "%02d.png"),
            "-frames:v",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(result),
        ],
        stage="cover_regression",
    )
    timeline = {"cover_frames": [15, 18], "total_frames": 30}
    if inserted_frames == 3:
        assert verify_cover(result, cover_path, timeline)["status"] == "PASS"
    else:
        with pytest.raises(ValueError, match="wrong decoded frames"):
            verify_cover(result, cover_path, timeline)


def test_real_cover_composition_preserves_timing_with_offset_source_and_audio(tmp_path):
    import wave

    from PIL import Image, ImageDraw

    from studio.core.ffmpeg import run_ffmpeg
    from studio.core.media_probe import probe
    from studio.social_video.funny_threads import compose_cover, verify_cover

    base = tmp_path / "base.png"
    cover = tmp_path / "cover.png"
    image = Image.new("RGB", (1080, 1920), "#152b24")
    image.save(base)
    ImageDraw.Draw(image).rectangle((30, 280, 1010, 620), fill="#ffdc5d")
    image.save(cover)
    source = tmp_path / "offset.mp4"
    run_ffmpeg(
        [
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(base),
            "-vf",
            "setpts=PTS+4/(30*TB)",
            "-frames:v",
            "30",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        stage="offset_source",
    )
    audio = tmp_path / "mix.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0" * 48000 * 4)
    output = tmp_path / "draft.mp4"
    timeline = {"cover_frames": [15, 18], "total_frames": 30, "duration": 1.0}
    compose_cover(source, cover, audio, output, timeline)
    assert verify_cover(output, cover, timeline)["decoded_matches"] == [False, True, True, True, False]
    assert probe(output).has_audio
    assert probe(output).duration == pytest.approx(1.0, abs=0.05)
