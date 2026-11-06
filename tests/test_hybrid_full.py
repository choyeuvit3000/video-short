import pytest

from studio.social_video.hybrid_full import parts_for_shot, video_retime


def test_illustration_to_flow_boundary_covers_exact_scene_frames():
    shot = {"first_frame": 1761, "frames": 396}
    parts = parts_for_shot(shot, {"still_prefix_frames": 158, "still_path": "corrected.png"})
    assert parts[0]["first_frame"] + parts[0]["frames"] == parts[1]["first_frame"]
    assert sum(x["frames"] for x in parts) == 396
    assert parts[-1]["first_frame"] + parts[-1]["frames"] == 1761 + 396


@pytest.mark.parametrize("prefix", [-1, 396, 397, 2.5, True])
def test_invalid_illustration_prefix_cannot_hide_a_missing_flow_window(prefix):
    with pytest.raises(ValueError):
        parts_for_shot({"first_frame": 0, "frames": 396},
                       {"still_prefix_frames": prefix, "still_path": "frame.png"})


def test_unapproved_slowing_or_long_freeze_is_rejected():
    assert video_retime(190/24, 140, allow=False) == 1
    assert video_retime(190/24, 238, allow=False) == 1
    with pytest.raises(ValueError):
        video_retime(190/24, 251, allow=False)
    assert video_retime(190/24, 251, allow=True) == pytest.approx(1.056842105)
    with pytest.raises(ValueError):
        video_retime(190/24, 396, allow=True)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_invalid_video_duration_cannot_reach_ffmpeg(seconds):
    with pytest.raises(ValueError):
        video_retime(seconds, 100, allow=True)
