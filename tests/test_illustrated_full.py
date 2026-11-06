import json

import pytest

from studio.social_video.illustrated_full import captions, frame_shots, scene_signature


def test_shared_boundary_is_snapped_once_without_drift():
    shots = [{"start_seconds": 0, "end_seconds": 1.017},
             {"start_seconds": 1.017, "end_seconds": 2.494}]
    result = frame_shots(shots, 2.494)
    assert result[0]["first_frame"] + result[0]["frames"] == result[1]["first_frame"]
    assert sum(x["frames"] for x in result) == round(2.494 * 30)


@pytest.mark.parametrize("shots,seconds", [
    ([{"start_seconds": .1, "end_seconds": 2}], 2),
    ([{"start_seconds": 0, "end_seconds": 1}, {"start_seconds": 1.2, "end_seconds": 2}], 2),
    ([{"start_seconds": 0, "end_seconds": 1}, {"start_seconds": .9, "end_seconds": 2}], 2),
    ([{"start_seconds": 0, "end_seconds": 1}], 2),
    ([{"start_seconds": 0, "end_seconds": .001}], .001),
    ([{"start_seconds": 0, "end_seconds": float("inf")}], 2),
])
def test_missing_overlapping_or_empty_frames_are_rejected(shots, seconds):
    with pytest.raises(ValueError):
        frame_shots(shots, seconds)


def test_captions_reuse_real_onset_and_actual_story_title(tmp_path):
    timing = tmp_path / "words.json"
    timing.write_text(json.dumps({"timing_source": "manual", "words": [
        {"text": "Xin", "start_ms": 230, "end_ms": 500},
        {"text": "chào.", "start_ms": 510, "end_ms": 850}]}), encoding="utf-8")
    (tmp_path / "voice_manifest.json").write_text(json.dumps({
        "body": [{"seconds": 1.2}], "timing_files": [str(timing)]}), encoding="utf-8")
    (tmp_path / "vi.json").write_text(json.dumps({"title": "Một truyện khác"}), encoding="utf-8")
    result = captions(tmp_path, tmp_path, 1.2)
    assert result["pages"][0]["start"] == .23
    assert "Một truyện khác" in (tmp_path / "captions.ass").read_text(encoding="utf-8-sig")
    assert "Chiếc giày" not in (tmp_path / "captions.ass").read_text(encoding="utf-8-sig")


def test_moving_one_cut_invalidates_only_its_two_neighboring_scenes():
    before = frame_shots([{"start_seconds": i, "end_seconds": i + 1} for i in range(5)], 5)
    after = frame_shots([{"start_seconds": 0, "end_seconds": 1},
                         {"start_seconds": 1, "end_seconds": 2.2},
                         {"start_seconds": 2.2, "end_seconds": 3},
                         {"start_seconds": 3, "end_seconds": 4},
                         {"start_seconds": 4, "end_seconds": 5}], 5)
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True))
               if scene_signature(a, "image", "captions") != scene_signature(b, "image", "captions")]
    assert changed == [1, 2]
