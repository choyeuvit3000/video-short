import pytest

from studio.core.subtitles import Word
from studio.social_video.speech_spelling import for_alignment
from studio.social_video.voice_repair import validate


def words(text):
    return [Word(t, i * 100, i * 100 + 80) for i, t in enumerate(text.split())]


def test_southern_tone_ambiguity_retains_raw_words_and_exact_timing():
    raw = words("Dưới chân là đôi dép nhựa ngã vàng.")
    normalized, report = for_alignment("Dưới chân là đôi dép nhựa ngả vàng.", raw, southern=True)
    assert raw[6].text == "ngã" and normalized[6].text == "ngả"
    assert normalized[6].start_ms == raw[6].start_ms
    assert report == [{"expected": "ngả", "raw": "ngã", "start_ms": 600, "end_ms": 680}]
    assert not for_alignment("Dưới chân là đôi dép nhựa ngả vàng.", raw)[1]


@pytest.mark.parametrize("raw", ["Thắt đi đò.", "Đi đò.", "Khách phi đò."])
def test_tone_handling_cannot_hide_missing_or_changed_onsets(raw):
    with pytest.raises(ValueError, match="Onset"):
        validate("Khách đi đò.", words(raw), 1, southern=True)


def test_numeric_marker_is_never_recovered_by_spelling_equivalence():
    text = "Năm phẩy hai người."
    assert for_alignment(text, words("Năm phẫy hai người."), southern=True)[1] == []
    with pytest.raises(ValueError, match="Onset"):
        validate(text, words("Năm hai người."), 1, southern=True)


def test_gium_dum_is_a_limited_regional_word_pair_not_a_consonant_rewriter():
    assert for_alignment("Con đem giùm má.", words("Con đem dùm má."), southern=True)[1]
    raw = words("Dạ đây.")
    assert for_alignment("Giạ đây.", raw, southern=True) == (raw, [])
