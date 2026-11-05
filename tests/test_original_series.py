import pytest

from studio.core.errors import ManualGateRequired
from studio.social_video.reddit_edit import partition
from studio.social_video.story_source import credit, labels, mode


def test_original_story_never_claims_a_reddit_or_threads_source():
    story = {"platform": "original_fiction", "title": "Mẫu", "inspirations": [{"work": "Liêu trai"}]}
    assert mode(story) == "original_story"
    assert labels(story) == ("Truyện kỳ dị", "Sáng tác lấy cảm hứng dân gian")
    assert "Truyện hư cấu" in credit(story) and "Liêu trai" in credit(story)
    assert "r/" not in credit(story) and "Threads" not in credit(story)


def test_explicit_five_episodes_are_not_merged_when_the_whole_story_fits():
    groups = [[f"Tập {i} có lời đọc."] for i in range(5)]
    vi = {"episode_sentence_ranges": [[i, i + 1] for i in range(5)]}
    parts = partition(groups, [(None, 20)] * 5, vi=vi)
    assert len(parts) == 5 and [part[0][1] for part in parts] == list(range(5))


@pytest.mark.parametrize("ranges", [[[0, 1], [2, 3]], [[0, 1]], [[0, 2], [1, 3]], [[0, 4]]])
def test_invalid_episode_coverage_stops_instead_of_losing_or_reordering_speech(ranges):
    with pytest.raises(ManualGateRequired):
        partition([["Một."], ["Hai."], ["Ba."]], [(None, 20)] * 3, vi={"episode_sentence_ranges": ranges})


def test_episode_cannot_split_a_spoken_group_or_hide_an_overrun():
    with pytest.raises(ManualGateRequired):
        partition([["Một.", "Hai."]], [(None, 20)] * 2, vi={"episode_sentence_ranges": [[0, 1], [1, 2]]})
    with pytest.raises(ManualGateRequired):
        partition([["Một."], ["Hai."]], [(None, 90)] * 2, vi={"episode_sentence_ranges": [[0, 2]]})


def test_horror_background_uses_longest_reviewed_clip_at_a_random_phase(tmp_path, monkeypatch):
    import random

    from studio.social_video import bgclips

    short, long = tmp_path / "short.mp4", tmp_path / "long.mp4"
    monkeypatch.setattr(bgclips, "horror_pool", lambda: [short, long])
    monkeypatch.setattr(bgclips, "_duration", lambda path: 60 if path == long else 20)
    monkeypatch.setattr(bgclips, "_crop", lambda *a: "")
    monkeypatch.setattr(bgclips, "USAGE", tmp_path / "usage.json")
    source, start, crop = bgclips.pick(70, random.Random(1), family="horror")
    assert source == long and 0 < start < 60
