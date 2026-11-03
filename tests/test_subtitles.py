from studio.core.subtitles import (
    Cue,
    Word,
    build_ass,
    check_cues,
    chunks_to_cues,
    estimate_words,
    group_words,
    parse_srt,
    read_srt,
    shift_cues,
    write_srt,
)


def test_srt_roundtrip_vietnamese(tmp_path):
    cues = [Cue(0, 1500, "Xin chào các bạn"), Cue(1500, 3200, "Đây là phụ đề tiếng Việt")]
    p = tmp_path / "a.srt"
    write_srt(p, cues)
    back = read_srt(p)
    assert [(c.start_ms, c.end_ms, c.text) for c in back] == [(c.start_ms, c.end_ms, c.text) for c in cues]


def test_srt_shift_8000ms():
    cues = parse_srt("1\n00:00:00,500 --> 00:00:02,000\nmột\n\n2\n00:00:02,000 --> 00:00:03,250\nhai\n")
    shifted = shift_cues(cues, 8000)
    assert (shifted[0].start_ms, shifted[0].end_ms) == (8500, 10000)
    assert (shifted[1].start_ms, shifted[1].end_ms) == (10000, 11250)


def test_check_cues_order_and_overrun():
    errs = check_cues([Cue(2000, 3000, "a"), Cue(1000, 1500, "b"), Cue(900, 900, "c")], duration_ms=2200)
    assert any("not monotonic" in e for e in errs)
    assert any("ends after the video" in e for e in errs)
    assert any("invalid time range" in e for e in errs)
    assert check_cues([Cue(0, 1000, "a"), Cue(1000, 2000, "b")], duration_ms=2000) == []


def test_estimate_and_group_words():
    words = estimate_words("Một hai ba bốn năm sáu bảy", 3500)
    assert len(words) == 7
    assert words[0].start_ms == 0 and words[-1].end_ms <= 3500
    assert all(a.end_ms <= b.start_ms for a, b in zip(words, words[1:], strict=False))
    chunks = group_words(words, max_words=3, max_chars=18)
    assert all(len(c) <= 3 for c in chunks)
    cues = chunks_to_cues(chunks)
    assert cues[0].text == "Một hai ba"


def test_build_ass_highlight():
    words = [Word("Xin", 0, 300), Word("chào", 300, 700), Word("bạn", 700, 1000)]
    style = {"font": "Arial", "bold": True, "color": "#FFFFFF", "highlight_color": "#FFE14D",
             "outline_color": "#000000", "outline": 4, "shadow": 0, "mode": "highlight", "size_scale": 1.0}
    ass, cues = build_ass(words, width=360, height=640, style=style,
                          caption={"font_size": 28, "margin_v": 200, "margin_h": 30, "max_words": 3, "max_chars": 18})
    assert "PlayResY: 640" in ass
    assert ass.count("Dialogue:") == 3  # one event per highlighted word
    assert "chào" in ass
    assert cues[0].text.replace("\n", " ") == "Xin chào bạn"


def test_caption_style_can_ask_for_longer_chunks():
    words = [Word(w, i * 300, i * 300 + 280) for i, w in enumerate("một hai ba bốn năm sáu".split())]
    style = {"mode": "plain"}
    caption = {"font_size": 28, "max_words": 3, "max_chars": 40}
    _, cues = build_ass(words, width=360, height=640, style=style, caption=caption)
    assert [c.text for c in cues] == ["một hai ba", "bốn năm sáu"]
    _, cues = build_ass(words, width=360, height=640, style={**style, "max_words": 4}, caption=caption)
    assert [c.text for c in cues] == ["một hai ba bốn", "năm sáu"]
