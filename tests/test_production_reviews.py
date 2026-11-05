import json
from pathlib import Path

import pytest

from studio.core import creative_brief as cb
from studio.core import user_review as r
from studio.core.errors import ManualGateRequired, ValidationError
from studio.core.speech_edit import issues, normalize


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("5/10", "năm trên mười"),
        ("ngày 5/10", "ngày năm tháng mười"),
        ("15.3.2021", "mười lăm tháng ba năm hai nghìn không trăm hai mươi mốt"),
        ("5,2%", "năm phẩy hai phần trăm"),
        ("12.000", "mười hai nghìn"),
        ("gọi 911", "gọi chín một một"),
        ("AI giúp ai?", "trí tuệ nhân tạo giúp ai?"),
    ],
)
def test_speech_context(raw, spoken):
    assert normalize(raw) == spoken
    assert issues(spoken) == []


def test_names_and_ratio_choice():
    assert normalize("Megan gặp Megan", lexicon={"Megan": "Lan"}) == "Lan gặp Lan"
    assert normalize("5/10", slash="phần") == "năm phần mười"
    assert issues("Steven đến lúc 5 giờ")


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "project_id": "review_test",
                "workflow": "knowledge_explainer",
                "language": "vi",
                "audio": {"voice_profile": "mock-vi"},
                "scenes": [{"scene_id": "s1", "narration": "Có năm người."}],
            }
        )
    )
    cb.prepare(tmp_path, {"goal": "Explain", "audience": "Vietnamese viewer", "voice": "mock-vi"})
    return tmp_path


def approve_script(folder):
    r.prepare(folder, "script")
    r.approve(folder, "script", "User fixture: this script and its choices are approved")


def make_voice(folder):
    p = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    p["scenes"][0]["audio_path"] = "audio/take.wav"
    (folder / "audio").mkdir(exist_ok=True)
    (folder / "audio/take.wav").write_bytes(b"approved sample fixture")
    (folder / "project.json").write_text(json.dumps(p), encoding="utf-8")
    (folder / "work").mkdir(exist_ok=True)
    (folder / "work/timeline.json").write_text(json.dumps({"scenes": [{"timing_source": "faster_whisper"}]}))
    r.prepare(folder, "voice")


def test_old_agent_approval_does_not_authorize_voice(folder):
    with pytest.raises(ManualGateRequired):
        cb.approve(folder, "Codex")
    with pytest.raises(ManualGateRequired):
        r.require(folder, "script")
    approve_script(folder)
    r.require(folder, "script")
    p = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    p["scenes"][0]["narration"] = "Đã sửa câu này."
    (folder / "project.json").write_text(json.dumps(p))
    with pytest.raises(ManualGateRequired):
        r.require(folder, "script")


def test_voice_approval_is_bound_to_audio_and_script(folder):
    approve_script(folder)
    make_voice(folder)
    with pytest.raises(ManualGateRequired):
        r.require(folder, "voice")
    r.approve(folder, "voice", "User fixture: listened and approved")
    r.require(folder, "voice")
    (folder / "audio/take.wav").write_bytes(b"changed")
    with pytest.raises(ManualGateRequired):
        r.require(folder, "voice")
    with pytest.raises(ValidationError):
        r.approve(folder, "voice", "approve stale packet")


def test_voice_approval_includes_timed_layout_preview(folder):
    approve_script(folder)
    make_voice(folder)
    preview = folder / "work/previews/story.mp4"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"timed layout preview")
    packet = r.prepare(folder, "voice")
    assert any(x["path"] == str(preview.resolve()) for x in packet["payload"]["files"])
    assert "![story.mp4]" in (folder / "REVIEW_VOICE.md").read_text(encoding="utf-8")
    r.approve(folder, "voice", "User fixture: narration and timed layout accepted")
    r.require(folder, "voice")
    preview.write_bytes(b"different layout preview")
    with pytest.raises(ManualGateRequired):
        r.require(folder, "voice")


def test_explicit_batch_waiver_is_not_a_fake_listening_approval(folder):
    r.write(
        folder / "review_waiver.json",
        {
            "reviewer": "user",
            "project_id": folder.name,
            "message": "User fixture: finish this batch without further approval requests",
            "stages": ["script", "voice", "final"],
        },
    )
    assert r.require(folder, "script")["authorization"] == "USER_WAIVED_CHECKPOINT"
    with pytest.raises(ValidationError):
        r.require(folder, "voice")  # No actual speech yet.
    make_voice(folder)
    assert r.prepare(folder, "voice")["status"] == "USER_REVIEW_WAIVED"
    r.require(folder, "voice")
    assert not (folder / "user_reviews.json").exists()
    with pytest.raises(ValidationError):
        r.require(folder, "final")  # No technically checked video yet.
    data = r.read(folder / "review_waiver.json")
    data["project_id"] = "another-video"
    r.write(folder / "review_waiver.json", data)
    with pytest.raises(ManualGateRequired):
        r.require(folder, "script")


def test_voice_packet_accepts_non_numeric_asr_evidence(folder):
    approve_script(folder)
    make_voice(folder)
    r.write(
        folder / "work/speech_checks/phrase_recheck.json",
        {"checks": [{"expected": "Có năm người.", "raw_transcript": "Có năm người."}]},
    )
    assert r.prepare(folder, "voice")["status"] == "WAITING_USER"


def test_three_approvals_limit_and_idempotent_response(folder):
    approve_script(folder)
    r.approve(folder, "script", "same accepted response")
    assert len(r.read(folder / "user_reviews.json")["approvals"]) == 1
    make_voice(folder)
    r.approve(folder, "voice", "User fixture: sound accepted")
    # Third accepted review used on a revised voice; a fourth cannot be created silently.
    (folder / "audio/take.wav").write_bytes(b"revised voice")
    r.prepare(folder, "voice")
    r.approve(folder, "voice", "User fixture: revision accepted")
    (folder / "audio/take.wav").write_bytes(b"fourth voice")
    r.prepare(folder, "voice")
    with pytest.raises(ManualGateRequired, match="review_budget"):
        r.approve(folder, "voice", "fourth approval")


def test_karaoke_phrase_stays_one_event_and_has_no_box():
    import yaml

    from studio.core.subtitles import Word, build_ass

    style = yaml.safe_load(Path("assets/shared/caption_styles/clean_box.yaml").read_text(encoding="utf-8"))
    words = [Word(w, i * 200, (i + 1) * 200) for i, w in enumerate("Mỗi người quen nối thêm một người khác".split())]
    text, cues = build_ass(
        words, width=1080, height=1920, style=style, caption={"font_size": 78, "margin_v": 510, "margin_h": 140}
    )
    assert "\\kf" in text and "\\fad(50,50)" in text
    assert text.count("Dialogue:") == len(cues) < len(words)
    assert style["box"] is False and style["outline"] < 3


def test_alignment_does_not_disguise_failed_recognition():
    from studio.core.errors import ProviderUnavailable
    from studio.core.subtitles import Word
    from studio.providers.align import map_onto_text

    with pytest.raises(ProviderUnavailable):
        map_onto_text("Có năm người trung gian.", [Word("khác", 0, 500)], 1500, strict=True)
    with pytest.raises(ProviderUnavailable):
        map_onto_text("Có năm người.", [], 1500, strict=True)
    got = map_onto_text("năm trên mười", [Word("5/10", 0, 900), Word("subscribe", 900, 900)], 900, strict=True)
    assert [w.text for w in got] == ["năm", "trên", "mười"]
    assert all(0 <= w.start_ms < w.end_ms <= 900 for w in got)


def test_reddit_parts_and_cold_open():
    from studio.social_video.reddit_edit import hook_texts, partition

    parts = partition([["Một"], ["Hai"], ["Ba"]], [(Path("a"), 35), (Path("b"), 35), (Path("c"), 35)], 75)
    assert len(parts) == 3
    assert hook_texts({"hook": "Có ai đang đứng sau lưng tôi."}, parts)[0].startswith("Có ai")
    with pytest.raises(ValidationError):
        hook_texts({"hook": "Phần hai. Tôi tỉnh dậy."}, parts)


def test_final_requires_fresh_qc_and_three_user_acceptances(folder, settings, monkeypatch):
    import studio.core.project as project

    context_type = project.ProjectContext
    monkeypatch.setattr(project, "ProjectContext", lambda path: context_type(path, settings=settings))
    approve_script(folder)
    make_voice(folder)
    r.approve(folder, "voice", "User fixture: voice accepted")
    ctx = project.ProjectContext(folder)
    ctx.final_video.parent.mkdir(exist_ok=True)
    ctx.final_video.write_bytes(b"video fixture")
    qpath = ctx.result_path("qc_report.json")
    r.write(qpath, {"status": "PASS", "sha256": "stale hash"})
    with pytest.raises(ValidationError, match="review_qc"):
        r.prepare(folder, "final")
    r.write(qpath, {"status": "PASS", "sha256": r.sha(ctx.final_video)})
    r.prepare(folder, "final")
    r.approve(folder, "final", "User fixture: final accepted")
    assert len(r.read(folder / "user_reviews.json")["approvals"]) == 3
    assert r.read(qpath)["editorial"] == "APPROVED"
    r.require(folder, "final")
    ctx.final_video.write_bytes(b"changed video")
    with pytest.raises(ValidationError):
        r.require(folder, "final")


def test_voice_change_is_reviewed_at_second_checkpoint(folder):
    approve_script(folder)
    make_voice(folder)
    p = r.read(folder / "project.json")
    p["audio"]["speed"] = 1.1
    r.write(folder / "project.json", p)
    r.require(folder, "script")
    with pytest.raises(ValidationError):
        r.approve(folder, "voice", "cannot accept the old packet")


def test_gate_is_before_cache_or_render_budget(folder, settings, monkeypatch):
    from studio.core.project import ProjectContext
    from studio.pipeline import fingerprint, runner

    settings.data["reviews"]["required"] = True
    settings.data["planning"]["required"] = True
    ctx = ProjectContext(folder, settings=settings)
    called = []
    monkeypatch.setattr(fingerprint, "up_to_date", lambda *args: called.append("cache") or True)
    monkeypatch.setattr(cb, "reserve_render", lambda *args: called.append("budget"))
    with pytest.raises(ManualGateRequired):
        runner.run_pipeline(ctx, runner.RunOptions(only=["render"], force=True))
    assert called == []


def test_light_knowledge_canvas_uses_ink_captions(folder, settings):
    from studio.core.project import ProjectContext
    from studio.renderers.render import caption_style

    p = r.read(folder / "project.json")
    p.setdefault("video", {})["background"] = "color:#F5F1E8"
    p["video"]["caption_style"] = "clean_box"
    r.write(folder / "project.json", p)
    style = caption_style(ProjectContext(folder, settings=settings))
    assert style["color"] == "#182532" and style["shadow"] == 0 and style["outline"] < 1


def test_full_story_is_recomposed_landscape(tmp_path, monkeypatch):
    import shutil

    from studio.core.ffmpeg import run_ffmpeg
    from studio.core.media_probe import probe
    from studio.social_video import quality, reddit_full, story_sound
    from studio.core.subtitles import Word, save_words

    from .conftest import HAS_FFMPEG, color_clip

    if not HAS_FFMPEG:
        pytest.skip("ffmpeg unavailable")
    bg = color_clip(tmp_path / "bg.mp4", "blue", 2)
    audio = tmp_path / "take.wav"
    run_ffmpeg(
        ["-f", "lavfi", "-i", "sine=frequency=330:duration=1", "-ar", "48000", "-ac", "2", str(audio)], stage="fixture"
    )
    monkeypatch.setattr(reddit_full.bgclips, "planned", lambda *args, **kw: (bg, 0, ""))
    monkeypatch.setattr(story_sound, "mix", lambda folder, part, src, dst, seconds: shutil.copy2(src, dst))
    wp = tmp_path / "words.json"
    save_words(wp, [Word("Một", 100, 250), Word("câu", 250, 500), Word("chuyện.", 500, 850)], source="manual")
    r.write(tmp_path / "voice_manifest.json", {"timing_files": [str(wp), str(wp)]})
    monkeypatch.setattr(reddit_full, "FINAL_OUTPUT", tmp_path / "output")
    sizes = []

    def publish_fixture(draft, out, cfg):
        sizes.append((cfg["video"]["width"], cfg["video"]["height"]))
        shutil.copy2(draft, out)

    monkeypatch.setattr(quality, "publish", publish_fixture)
    out = reddit_full.export_full(
        "fixture",
        {"sub": "nosleep", "author": "fixture"},
        {"title": "Câu chuyện mẫu"},
        [["Một câu chuyện.", "Một lời kết."]],
        [(audio, 1), (audio, 1)],
        {"reddit": {}, "video": {}},
        tmp_path,
    )
    info = probe(out)
    assert sizes == [(1920, 1080)] and (info.width, info.height) == (1920, 1080)
    assert abs(info.duration - 2) < 0.1


def test_native_subtitles_keep_stable_size(tmp_path):
    from studio.social_video.subs import write_ass

    out = tmp_path / "captions.ass"
    words = [
        {"text": t, "start": i * 0.2, "end": (i + 1) * 0.2}
        for i, t in enumerate("Có một người đang đứng sau lưng tôi".split())
    ]
    write_ass(words, 0.25, out, 1080, 1920, "Arial")
    text = out.read_text(encoding="utf-8")
    assert "\\kf" in text and "fscx108" not in text
    assert text.count("Dialogue:") < len(words)


def test_resuming_keeps_accepted_voice_and_timings(folder, settings, monkeypatch):
    from studio.core.project import ProjectContext
    from studio.pipeline import voice

    approve_script(folder)
    make_voice(folder)
    r.approve(folder, "voice", "User fixture: accepted audio")
    settings.data["reviews"]["required"] = True
    monkeypatch.setattr(voice, "_synthesize_all", lambda *a: pytest.fail("regenerated accepted audio"))
    monkeypatch.setattr(voice, "_words_for", lambda *a: pytest.fail("realigned accepted timings"))
    assert voice.run_voice(ProjectContext(folder, settings=settings))["scenes"][0]["timing_source"] == "faster_whisper"


def test_reddit_cache_tracks_speed_and_hooks_use_omni(tmp_path, monkeypatch):
    import copy
    import wave
    from types import SimpleNamespace

    from studio.social_video import reddit

    profile = SimpleNamespace(id="fixture", provider="mock", params={})
    monkeypatch.setattr("studio.core.voice_policy.social_profile", lambda cfg: (profile, tmp_path))
    engines = []

    def synth_fixture(texts, path, cfg, gap, roles):
        engines.append(cfg["engines"])
        path.mkdir(parents=True, exist_ok=True)
        wav = path / "take.wav"
        with wave.open(str(wav), "wb") as fh:
            fh.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
            fh.writeframes(b"\0" * 19200)
        return [(wav, 0.1)] * len(texts)

    monkeypatch.setattr(reddit.tts, "voice_sentences", synth_fixture)
    cfg = {
        "tts": {"engines": ["omnivoice"], "omnivoice": {"speed": 1}},
        "reddit": {"narration_speed": 1.1, "wait_for_vivibe": False},
    }
    first = reddit.voice_story(["Có tiếng chuột."], cfg, {}, tmp_path / "body")
    changed = copy.deepcopy(cfg)
    changed["reddit"]["narration_speed"] = 1.15
    second = reddit.voice_story(["Có tiếng chuột."], changed, {}, tmp_path / "body")
    assert first[0][0] != second[0][0]
    reddit.voice_free("Có ai sau lưng tôi.", tmp_path / "hook", cfg, "narrator")
    assert engines[-1] == ["omnivoice"]


def test_name_map_updates_dialogue_cast(tmp_path):
    from studio.core.speech_edit import project_edit

    r.write(
        tmp_path / "vi.json",
        {"paragraphs": ["Megan nói."], "closing_question": False, "character_map": {"Megan": "Lan"}, "cast": {"names": {"Megan": "female"}}},
    )
    project_edit(tmp_path)
    vi = r.read(tmp_path / "vi.json")
    assert vi["paragraphs"] == ["Lan nói."] and vi["cast"]["names"] == {"Lan": "female"}
