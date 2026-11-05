"""Editorial lint is evidence for review, never creator or speech-timing approval."""

import json

import pytest

from studio.social_video.story_editorial import review_draft, write_review
from studio.social_video.story_policy import PROMPT, original_story_prompt


def draft(text, **fields):
    return {"fiction": True, "episodes": [{"title": "Mẫu", "narration": text, **fields}]}


def test_clean_draft_still_requires_human_and_real_timing():
    text = "Khách của tôi đã chết. Tôi nghe nước nhỏ. Bà kéo tay tôi. Tôi đứng lại."
    report = review_draft(draft(text, sensory_anchor="nghe nước nhỏ", climax_start="Bà kéo tay tôi."))
    item = report["episodes"][0]
    assert item["space_separated_units"] == len(text.split())
    assert item["warnings"] == []
    assert report["creator_approved"] is False and report["actual_duration"] == "NOT_MEASURED"
    assert item["sensory_first_fifteen_seconds"] == item["hook_first_three_seconds"] == "PENDING_ACTUAL_SPEECH_TIMING"
    assert item["standalone_hook_semantics"] == "CREATOR_REVIEW_REQUIRED"


def test_body_length_is_not_a_forced_duration_or_global_short_sentence_rule():
    body = " ".join(["chuyện"] * 35) + "."
    text = "Tôi gặp người đã chết. Mùi bùn xộc lên. " + body + " Cửa mở. Tôi chạy."
    report = review_draft(draft(text, sensory_anchor="Mùi bùn", climax_start="Cửa mở."))
    assert report["episodes"][0]["long_climax_sentences"] == []
    assert report["actual_duration"] == "NOT_MEASURED"


def test_missing_or_late_sensory_phrase_cannot_be_marked_verified():
    text = "Tôi gặp người đã chết. " + " ".join(["chuyện"] * 150) + ". Mùi bùn xộc lên."
    item = review_draft(draft(text, sensory_anchor="Mùi bùn", climax_start="Mùi bùn"))["episodes"][0]
    assert item["sensory_units_before"] > 150
    assert item["sensory_first_fifteen_seconds"] == "PENDING_ACTUAL_SPEECH_TIMING"
    missing = review_draft(draft(text, sensory_anchor="tiếng cười", climax_start="Mùi bùn"))["episodes"][0]
    assert any(x.startswith("SENSORY_ANCHOR_MISSING") for x in missing["warnings"])


def test_recap_digits_and_long_climax_are_reviewed_without_rewriting():
    text = "Ở tập trước tôi đã gặp 2 người. Mùi bùn xộc lên. " + " ".join(["chạy"] * 18) + "."
    data = draft(text, sensory_anchor="Mùi bùn", climax_start=" ".join(["chạy"] * 18))
    item = review_draft(data)["episodes"][0]
    assert any(x.startswith("RECAP_OPENING") for x in item["warnings"])
    assert any(x.startswith("SPOKEN_DIGITS") for x in item["warnings"])
    assert item["long_climax_sentences"][0]["units"] == 18
    assert data["episodes"][0]["narration"] == text


def test_report_never_overwrites_the_draft_or_grants_approval(tmp_path):
    source = tmp_path / "draft.json"
    source.write_text(
        json.dumps(draft("Tôi nghe nước nhỏ.", sensory_anchor="nghe nước nhỏ", climax_start="Tôi nghe")),
        encoding="utf-8",
    )
    before = source.read_bytes()
    output, report = write_review(source)
    assert output.is_file() and source.read_bytes() == before
    assert report["creator_approved"] is False
    with pytest.raises(ValueError, match="overwrite"):
        write_review(source, source)


def test_factual_sources_are_not_silently_treated_as_fiction():
    with pytest.raises(ValueError, match="fiction"):
        review_draft({"fiction": False, "episodes": [{"narration": "Nguồn công khai."}]})
    prompt = original_story_prompt()
    assert "Bổ sung giác quan" in prompt and "Bổ sung câu mở độc lập" in prompt and "Bổ sung cao trào" in prompt
    assert "Không bịa âm thanh, mùi, xúc giác" in PROMPT
