import json

import pytest

from studio.core.config import load_yaml
from studio.core.subtitles import Word, build_ass, group_phrases
from studio.providers.source.article import Article
from studio.workflows.news_planner import normalize_beat, plan_scenes, unverified_numbers

from .conftest import color_image, make_project


def test_unlimited_content_does_not_drop_article_ending():
    from studio.workflows.newspaper import _passthrough

    art = Article(title="Bản tin", lead="Thông tin mở đầu.", paragraphs=[
        "Nội dung quan trọng cần giải thích đầy đủ. " * 40,
        "Điều kiện cuối cùng phải được giữ lại."])
    for options in ({}, {"target_sec": None}, {"target_sec": 1}):
        script = _passthrough(art, options, "vi")
        assert script["beats"][-1]["narration"].endswith("Điều kiện cuối cùng phải được giữ lại.")


def test_dense_cards_get_more_reading_time(settings):
    from studio.workflows.news_planner import reading_hold

    cfg = load_yaml(settings.path("assets") / "shared/layouts/news.yaml")
    short = reading_hold("text_card", {"title": "Hướng dẫn", "points": ["Đọc bài mẫu"]}, cfg)
    dense = reading_hold("text_card", {"title": "Hướng dẫn", "points": [
        "Tham khảo đầy đủ điều kiện và thông tin từ nguồn chính thức."] * 4}, cfg)
    assert dense > short >= 3


def test_content_first_prompt_without_duration_cap(tmp_path, settings, monkeypatch):
    from studio.workflows.newspaper import _llm_script

    ctx = make_project(tmp_path / "content_first", settings, workflow="newspaper")
    seen = []

    def fake_generate(ctx, task, prompt, schema, **kwargs):
        seen.append(prompt)
        return {"beats": []}, "test"

    monkeypatch.setattr("studio.workflows.newspaper.generate_json", fake_generate)
    _llm_script(ctx, Article(title="Tin thử", lead="Đầy đủ nội dung."), {}, False)
    assert "No duration or word limit" in seen[0]
    assert "as many as the story needs" in seen[0]
    assert "{{" not in seen[0]


def test_more_images_per_idea_keep_commons_provenance(tmp_path, settings, monkeypatch):
    from studio.providers.images import Photo
    from studio.workflows.newspaper import stage_news_media

    ctx = make_project(tmp_path / "more_photos", settings, workflow="newspaper",
                       options={"extra_images": "commons", "max_extra_images": 2})
    Article(title="Thư viện mới", lead="Sách và phòng đọc.").save(ctx.dir / "source/article.json")
    (ctx.work / "script.json").write_text(json.dumps({"beats": [
        {"image_query": "library reading room"}, {"image_query": "books library"}]}), encoding="utf-8")

    def fake_find(cache, query, stem, *, avoid):
        file = color_image(stem.with_suffix(".png"), "blue")
        return file, Photo(query, "https://example.org/photo.png", "https://example.org/file", "Author",
                           "CC BY 4.0", "https://example.org/license", 1200, 800, "image/png")

    monkeypatch.setattr("studio.providers.images.find_photo", fake_find)
    stage_news_media(ctx, {})
    media = json.loads((ctx.work / "news/media.json").read_text(encoding="utf-8"))
    assert len(media) == 2 and [m["for_beat"] for m in media] == [0, 1]
    assert all(m["origin"] == "commons" and m["author"] == "Author" and m["license"] == "CC BY 4.0"
               for m in media)


def test_planner_different_topic_and_asset_roles(settings):
    cfg = load_yaml(settings.path("assets") / "shared/layouts/news.yaml")
    art = Article(title="Mở thư viện mới", lead="Bà Nguyễn Thu Lan cho biết thư viện có 2.000 cuốn sách.",
                  paragraphs=["Mở cửa từ 1.6.2026. Độc giả đăng ký miễn phí."], publisher="Bản tin thử")
    media = [
        {"path": "library.jpg", "caption": "Phòng đọc", "credit": "A"},
        {"path": "other.jpg", "caption": "Ông Trần Văn Nam - Giám đốc", "credit": "B"},
        {"path": "lan.jpg", "caption": "Bà Nguyễn Thu Lan - Đại diện thư viện", "credit": "C"},
        {"path": "books.jpg", "kind": "editorial", "origin": "commons", "for_beat": 2},
    ]
    beats = [
        {"role": "hook", "narration": "Thư viện mở cửa.", "headline": art.title},
        {"role": "quote", "narration": "Bà Lan cho biết...", "name": "Nguyễn Thu Lan", "image": 1},
        {"role": "fact", "narration": "Phòng đọc có nhiều sách."},
        {"role": "document", "narration": "Đăng ký miễn phí.", "points": ["Đăng ký miễn phí"]},
        {"role": "number", "narration": "Có 9.000 sách.", "value": "9.000", "unit": "cuốn sách"},
    ]
    plans = plan_scenes([normalize_beat(b) for b in beats], media, art, cfg)
    assert plans[1]["asset"]["path"] == "lan.jpg"  # ignore a requested photo of another person
    assert plans[2]["asset"]["path"] == "books.jpg"  # per-idea Commons photo
    assert plans[3]["layout"] == "text_card" and plans[3]["fallback"]
    assert plans[4]["layout"] == "editorial_photo" and plans[4]["notes"]
    assert plans[4]["asset"]["path"] == "library.jpg"  # don't borrow an unrelated Commons result


@pytest.mark.parametrize("number,valid", [("12.000", True), ("15/3/2021", True), ("14", True),
                                         ("15.3.2025", False), ("120", False), ("3.500", False)])
def test_numeric_source_guard(number, valid):
    assert (not unverified_numbers(number, "12.000 câu hỏi, trước 15.3.2021, đổi lịch trước 14 ngày")) == valid


def test_phrase_caption_preserves_words_and_disables_false_highlight():
    text = "Thí sinh chọn ngày thi, và được đổi lịch trước 14 ngày dự thi."
    words = [Word(w, i * 200, i * 200 + 180) for i, w in enumerate(text.split())]
    chunks = group_phrases(words, max_words=10, max_chars=40)
    assert [w.text for ch in chunks for w in ch] == text.split()
    style = {"lines": 2, "max_words": 10, "max_chars": 40, "line_chars": 22,
             "mode": "highlight", "box": True, "outline_alpha": 64}
    ass, cues = build_ass(words, width=1080, height=1920, style=style,
                          caption={"font_size": 60}, reliable_words=False)
    assert "\\c" not in ass and "\\N" in ass
    assert ass.count("Dialogue:") == len(cues)
    assert all(len(c.text.splitlines()) <= 2 for c in cues)
    assert " ".join(c.text.replace("\n", " ") for c in cues) == text
