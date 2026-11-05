import json
import random

import pytest

from studio.core import creative_brief as cb
from studio.core import user_review as review
from studio.core.errors import ManualGateRequired
from studio.social_video.story_source import credit, labels, mode


def test_threads_story_keeps_actual_attribution():
    story = {"platform": "threads", "author": "kimchi.hcm93", "url": "https://www.threads.com/@kimchi.hcm93/post/test"}
    assert labels(story) == ("Threads", "@kimchi.hcm93")
    assert mode(story) == "threads_story"
    assert "r/" not in credit(story) and "u/" not in credit(story)
    assert labels({"sub": "nosleep", "author": "author"}) == ("r/nosleep", "u/author")
    assert mode({}) == "reddit"


def test_exact_voice_speed_overrides_legacy_multiplier_once(tmp_path, monkeypatch):
    from studio.social_video.reddit import _tcfg

    (tmp_path / "vi.json").write_text(json.dumps({"paragraphs": ["Một câu chuyện."], "character_map": {}}))
    cb.prepare(
        tmp_path, {"voice": "vieneu-vi-thaison", "speech_speed": 1.25, "background": "random", "narration": "verbatim"}
    )
    monkeypatch.setattr(cb, "ensure_ready", lambda path: cb.prepare(path))
    cfg = {"tts": {"engines": ["vieneu"], "vieneu": {}}, "reddit": {"narration_speed": 1.1, "wait_for_vivibe": False}}
    cb.apply_social(tmp_path, cfg)
    assert cfg["reddit"]["background_family"] == "horror"
    assert cfg["reddit"]["narration_speed"] == 1.0
    assert _tcfg(cfg)["vieneu"]["speed"] == pytest.approx(1.25)


def test_source_changes_invalidate_story_script(tmp_path):
    review.write(tmp_path / "source.json", {"platform": "threads", "author": "one"})
    review.write(tmp_path / "vi.json", {"paragraphs": ["Một câu chuyện."], "character_map": {}})
    first = review.digest(review.payload(tmp_path, "script"))
    review.write(tmp_path / "source.json", {"platform": "threads", "author": "someone_else"})
    assert first != review.digest(review.payload(tmp_path, "script"))


def test_random_background_stays_the_reviewed_asset(tmp_path, monkeypatch):
    from studio.social_video import bgclips

    clip = tmp_path / "bg.mp4"
    clip.write_bytes(b"asset")
    calls = []
    monkeypatch.setattr(bgclips, "pick", lambda *a: calls.append(a) or (clip, 4, "crop=1,"))
    monkeypatch.setattr(bgclips, "_visible", lambda *a: True)
    first = bgclips.planned(tmp_path, 1, 50, random.Random(1))
    assert bgclips.planned(tmp_path, 1, 51, random.Random(999)) == first
    assert len(calls) == 1
    with pytest.raises(ManualGateRequired):
        bgclips.planned(tmp_path, 1, 50, random.Random(1), aspect=9 / 8)
    assert len(calls) == 1
    clip.write_bytes(b"changed")
    with pytest.raises(ManualGateRequired):
        bgclips.planned(tmp_path, 1, 50, random.Random(1))


def test_random_background_skips_unreadably_dark_footage(tmp_path, monkeypatch):
    from studio.social_video import bgclips

    dark, bright = tmp_path / "dark.mp4", tmp_path / "bright.mp4"
    dark.write_bytes(b"dark asset")
    bright.write_bytes(b"visible asset")
    candidates = iter([(dark, 1, "crop=1,"), (bright, 3, "crop=2,")])
    monkeypatch.setattr(bgclips, "pick", lambda *a: next(candidates))
    monkeypatch.setattr(bgclips, "_visible", lambda folder, part, candidate, seconds: candidate[0] == bright)
    assert bgclips.planned(tmp_path, 1, 45, random.Random(1)) == (bright, 3, "crop=2,")
    assert review.read(tmp_path / "background_plan.json")["slots"]["1"]["source"] == str(bright.resolve())


@pytest.mark.parametrize(("levels", "accepted"), [((0, 0, 0), False), ((0, 120, 120), False), ((120, 0, 120), True)])
def test_background_visibility_requires_a_visible_opening(tmp_path, monkeypatch, levels, accepted):
    from PIL import Image

    from studio.social_video import bgclips

    frames = iter(levels)

    def save_frame(args, **kwargs):
        Image.new("RGB", (160, 284), (next(frames),) * 3).save(args[-1])

    monkeypatch.setattr(bgclips, "_duration", lambda path: 65)
    monkeypatch.setattr("studio.core.ffmpeg.run_ffmpeg", save_frame)
    assert bgclips._visible(tmp_path, 1, (tmp_path / "bg.mp4", 8, ""), 40) == accepted
