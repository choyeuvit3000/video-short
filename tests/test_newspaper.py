import json

import pytest
from PIL import Image

from studio.core.errors import ManualGateRequired
from studio.pipeline.runner import RunOptions, run_pipeline
from studio.providers.source.article import (
    Article,
    article_from_markdown,
    looks_like_html,
    parse_article_html,
    split_credit,
)
from studio.workflows import load_workflow, project_defaults

from .conftest import color_image, make_project, needs_ffmpeg

# the shape of a laodong.vn article page: OG + JSON-LD, sapo duplicated as the first <p>, figures with
# figcaption credits, related-news blocks as <div>s and caption-less thumbnails inside <article>
PAGE = """<!doctype html><html><head><title>Đề mẫu ĐGNL | Báo Lao Động</title>
<meta property="og:title" content="Thời gian công bố đề mẫu và cách ôn bài Đánh giá năng lực">
<meta property="og:description" content=" PGS.TS Nguyễn Hoàng Hải cho hay, bài thi mẫu sẽ được công bố trước">
<meta property="og:image" content="https://cdn.example.vn/2021/1/27/lead.jpg?w=800&amp;h=420">
<meta property="og:url" content="https://laodong.vn/giao-duc/de-mau-874587.ldo">
<meta property="article:section" content="Giáo dục">
<meta property="article:published_time" content="2021-01-27T13:48:15+07:00">
<meta property="article:author" content="https://www.facebook.com/laodongonline">
<script type="application/ld+json">[{"@type":"BreadcrumbList"},{"@context":"https://schema.org",
 "@type":"NewsArticle","headline":"Thời gian công bố đề mẫu và cách ôn bài Đánh giá năng lực",
 "author":{"@type":"Person","name":"Hà Phương"},"publisher":{"@type":"Organization","name":"Báo Lao Động"}}]
</script><script>var x = "<p>not text</p>";</script></head><body>
<nav><p>Menu menu menu menu menu menu menu menu menu</p></nav>
<article class="article-detail"><h1 class="title">Thời gian công bố đề mẫu</h1>
<div class="chappeau"><p>PGS.TS Nguyễn Hoàng Hải cho hay, bài thi mẫu sẽ được công bố trước ngày 15.3.2021.</p></div>
<div class="art-body">
<figure class="insert-center-image"><img src="https://cdn.example.vn/2021/1/27/lead.jpg?w=660">
<figcaption>Bài thi mẫu sẽ được công bố trước ngày 15.3.2021. Ảnh minh hoạ: Thanh Chân.</figcaption></figure>
<p>Đối với kỳ thi Đánh giá năng lực, Đại học Quốc gia Hà Nội khẳng định bài thi phục vụ nhiều mục đích.</p>
<figure><img data-src="/Storage/2021/hai.JPG" src="data:image/gif;base64,R0lGOD">
<figcaption>PGS. TS Nguyễn Hoàng Hải - Phó Giám đốc Thường trực Đại học Quốc gia Hà Nội. Ảnh: NTCC.</figcaption>
</figure>
<p>PGS.TS Nguyễn Hoàng Hải cho hay: "Đề thi được rà soát từ hơn 12.000 câu hỏi của ngân hàng đề thi".</p>
</div>
<div class="pr"><div class="chapeau">Tin liên quan: một tin khác hoàn toàn không liên quan đến bài này.</div></div>
<figure class="_thumb"><img src="https://cdn.example.vn/thumb.jpg"></figure>
</article><footer><p>Bản quyền thuộc về Báo Lao Động, mọi hình thức sao chép phải ghi nguồn.</p></footer>
</body></html>"""

MD = """# Đề mẫu Đánh giá năng lực trước 15.3
url: https://example.vn/de-mau
publisher: Lao Động
section: Giáo dục
published: 2021-01-27
image: images/a.png | Thí sinh làm bài thi. Ảnh: Thanh Chân.
image: images/b.png | PGS. TS Nguyễn Hoàng Hải - Phó Giám đốc Thường trực ĐHQGHN. Ảnh: NTCC.

Bài thi mẫu của kỳ thi đánh giá năng lực sẽ được công bố trước ngày 15.3.2021.

Đại học Quốc gia Hà Nội khẳng định bài thi phục vụ nhiều mục đích. Công tác thi và tuyển sinh là tách biệt.

PGS.TS Nguyễn Hoàng Hải cho hay: "Đề thi được rà soát từ hơn 12.000 câu hỏi của ngân hàng đề thi".

Thí sinh được thay đổi thời gian thi trước 14 ngày dự thi. Cổng đăng ký mở từ ngày 1.4.2021.
"""


def test_split_credit():
    assert split_credit("Bài thi mẫu. Ảnh minh hoạ: Thanh Chân.") == ("Bài thi mẫu.", "Thanh Chân")
    assert split_credit("PGS. TS A - Phó Giám đốc. Ảnh: NTCC.") == ("PGS. TS A - Phó Giám đốc.", "NTCC")
    assert split_credit("Không có tác giả") == ("Không có tác giả", "")


def test_parse_article_html():
    assert looks_like_html(PAGE) and not looks_like_html(MD)
    a = parse_article_html(PAGE, "https://laodong.vn/giao-duc/de-mau-874587.ldo")
    assert a.title == "Thời gian công bố đề mẫu và cách ôn bài Đánh giá năng lực"
    assert a.lead.endswith("trước ngày 15.3.2021.")  # the complete sapo, not the cut og:description
    assert len(a.paragraphs) == 2 and "12.000" in a.paragraphs[1]  # no nav/footer/related/script text
    assert a.publisher == "Báo Lao Động" and a.author == "Hà Phương" and a.section == "Giáo dục"
    assert a.date_label == "27/01/2021"
    # og:image and the first figure are the same photo; the caption-less thumbnail is not an article image
    assert [i.src for i in a.images] == ["https://cdn.example.vn/2021/1/27/lead.jpg?w=660",
                                         "https://laodong.vn/Storage/2021/hai.JPG"]
    assert a.images[0].credit == "Thanh Chân" and a.images[1].caption.startswith("PGS. TS Nguyễn Hoàng Hải - ")


def test_full_size_image_url():
    from studio.workflows.newspaper import _full_size

    assert _full_size("https://cdn.vn/a.jpg?w=660&h=420&crop=auto&scale=both") == "https://cdn.vn/a.jpg"
    assert _full_size("https://cdn.vn/a.jpg?v=3&w=660") == "https://cdn.vn/a.jpg?v=3"
    assert _full_size("https://cdn.vn/a.jpg") == "https://cdn.vn/a.jpg"


def test_article_from_markdown():
    a = article_from_markdown(MD)
    assert a.publisher == "Lao Động" and a.published == "2021-01-27" and len(a.images) == 2
    assert a.lead.startswith("Bài thi mẫu") and len(a.paragraphs) == 3
    assert a.images[1].credit == "NTCC"


def _news_project(tmp_path, settings, name="news", **options):
    d = project_defaults(load_workflow(settings, "newspaper"), "test_9x16")
    d["options"] = {**d["options"], "rewrite": "none", **options}
    ctx = make_project(tmp_path / name, settings, workflow="newspaper", **d)
    color_image(ctx.dir / "images" / "a.png", (40, 90, 160), (1200, 800))
    color_image(ctx.dir / "images" / "b.png", (160, 80, 40), (800, 1000))
    (ctx.dir / "source" / "source.md").write_text(MD, encoding="utf-8")
    return ctx


def test_article_needs_a_source(tmp_path, settings):
    d = project_defaults(load_workflow(settings, "newspaper"), "test_9x16")
    ctx = make_project(tmp_path / "empty", settings, workflow="newspaper", **d)
    with pytest.raises(ManualGateRequired):
        run_pipeline(ctx, RunOptions(only=["article"]))
    assert "article.html" in (ctx.dir / "TODO_MANUAL.md").read_text(encoding="utf-8")


def test_newspaper_offline_stages(tmp_path, settings):
    ctx = _news_project(tmp_path, settings)
    run_pipeline(ctx, RunOptions(only=["article", "news_script", "news_media", "news_scenes"]))
    assert Article.load(ctx.dir / "source" / "article.json").section == "Giáo dục"
    media = json.loads((ctx.work / "news" / "media.json").read_text(encoding="utf-8"))
    assert [m["path"] for m in media] == ["images/a.png", "images/b.png"]  # not listed twice as own files
    p = ctx.project
    kinds = [s.scene_id.split("_", 1)[1] for s in p.scenes]
    assert kinds[0] == "headline" and "portrait_quote" in kinds
    for s in p.scenes:
        assert s.visual.type == "still" and (ctx.dir / s.visual.path).is_file()
        assert Image.open(ctx.dir / s.visual.overlay).size == (ctx.fmt.width, ctx.fmt.height)
    assert p.source.credit_text.startswith("Nguồn: Lao Động")
    assert {c["author"] for c in p.options["image_credits"]} == {"Thanh Chân", "NTCC"}


def test_newspaper_ai_beats(tmp_path, settings):
    """An AI answer pasted as work/llm/news_script.response.json: stat/card beats and bad indexes are handled."""
    ctx = _news_project(tmp_path, settings, rewrite="llm")
    run_pipeline(ctx, RunOptions(only=["article"]))
    beat = {"headline": "", "category": "", "name": "", "role": "", "value": "", "label": "", "note": ""}
    answer = {"title": "Đề mẫu ĐGNL", "description": "Theo Lao Động.", "hashtags": ["dgnl", "#tuyensinh"], "beats": [
        {**beat, "type": "photo", "narration": "Đề mẫu sẽ có trước 15.3.", "image": 0, "headline": "ĐỀ MẪU TRƯỚC 15.3"},
        {**beat, "type": "stat", "narration": "Đề được chọn từ hơn 12.000 câu hỏi.", "image": 9, "value": "12.000",
         "label": "câu hỏi", "note": "ngân hàng đề 2016"},
        {**beat, "type": "quote", "narration": "Ông Hải nói thí sinh nên tránh học tủ.", "image": 1,
         "name": "PGS.TS Nguyễn Hoàng Hải", "role": "Phó Giám đốc ĐHQGHN"},
        {**beat, "type": "card", "narration": "Lịch thi kéo dài đến tháng 11.", "image": 0},
        {**beat, "type": "quote", "narration": "Không có tên thì là ảnh thường.", "image": 0},
    ]}
    (ctx.work / "llm").mkdir(parents=True, exist_ok=True)
    (ctx.work / "llm" / "news_script.response.json").write_text(json.dumps(answer, ensure_ascii=False),
                                                                  encoding="utf-8")
    run_pipeline(ctx, RunOptions(only=["news_script", "news_media", "news_scenes"]))
    ids = [s.scene_id for s in ctx.project.scenes]
    assert ids == ["n01_headline", "n02_stat_card", "n03_portrait_quote", "n04_editorial_photo", "n05_editorial_photo"]
    assert ctx.project.hashtags == ["#dgnl", "#tuyensinh"]


@needs_ffmpeg
@pytest.mark.ffmpeg
def test_trim_silence(tmp_path):
    from studio.core.ffmpeg import run_ffmpeg
    from studio.core.media_probe import probe
    from studio.pipeline.voice import trim_silence

    clip = tmp_path / "v.mp3"  # 0.5 s silence, 1 s tone, 1 s silence - like an edge-tts take
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.5", "-f", "lavfi",
                "-i", "sine=frequency=300:sample_rate=24000:duration=1", "-f", "lavfi",
                "-i", "anullsrc=r=24000:cl=mono:d=1", "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1",
                str(clip)], stage="fixture")
    cut = trim_silence(clip)
    assert 400 <= cut <= 470  # 0.5 s minus the 60 ms kept
    assert 1.1 <= probe(clip).duration <= 1.35
    assert trim_silence(clip) <= 20  # already tight: (almost) nothing more to cut


@needs_ffmpeg
@pytest.mark.ffmpeg
@pytest.mark.parametrize("fmt", ["test_9x16", "test_16x9"])
def test_newspaper_end_to_end(tmp_path, settings, fmt):
    ctx = _news_project(tmp_path, settings, name=f"Tin {fmt}")
    ctx.project.video.format = fmt
    ctx.save()
    run_pipeline(ctx, RunOptions())
    rep = json.loads((ctx.output / "qc_report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "PASS", rep
    plan = json.loads((ctx.output / "scene_plan.json").read_text(encoding="utf-8"))
    assert plan[0]["start_sec"] == 0
    assert all(s["end_sec"] > s["start_sec"] for s in plan)
    assert all("layout" in s and "asset" in s and "narration" in s for s in plan)
    meta = (ctx.output / "metadata.md").read_text(encoding="utf-8")
    assert "Thanh Chân" in meta and "Nguồn: Lao Động" in meta


@needs_ffmpeg
@pytest.mark.ffmpeg
def test_news_rules_all_layouts_other_topic(tmp_path, settings):
    """A synthetic library bulletin exercises every layout through voice, captions, encode and packaging."""
    from studio.providers.source.article import ArticleImage

    ctx = _news_project(tmp_path, settings, name="Library bulletin")
    art = Article(title="Thư viện mở cửa", lead="Nguyễn Thu Lan giới thiệu thư viện có 2.000 cuốn sách.",
                  paragraphs=["Mở cửa từ 1.6.2026. Đăng ký miễn phí. Đổi thẻ từ 2.6.2026."],
                  publisher="Bản tin thử", images=[
                      ArticleImage(src="images/a.png", caption="Phòng đọc", credit="Test"),
                      ArticleImage(src="images/b.png", caption="Nguyễn Thu Lan - Đại diện thư viện", credit="Test")])
    art.save(ctx.dir / "source/article.json")
    beats = [
        {"role": "hook", "narration": "Thư viện mở cửa.", "headline": "THƯ VIỆN MỞ CỬA", "highlight": "MỞ CỬA"},
        {"role": "quote", "narration": "Nguyễn Thu Lan giới thiệu.", "name": "Nguyễn Thu Lan", "image": 1},
        {"role": "fact", "narration": "Phòng đọc mở cửa."},
        {"role": "number", "narration": "Có 2.000 cuốn sách.", "value": "2.000", "unit": "cuốn sách",
         "explain": "Tại thư viện"},
        {"role": "document", "narration": "Đăng ký miễn phí.", "points": ["Đăng ký miễn phí"]},
        {"role": "timeline", "narration": "Mở cửa từ tháng sáu.", "dates": [
            {"date": "1.6.2026", "text": "Mở cửa"}, {"date": "2.6.2026", "text": "Đổi thẻ"}]},
        {"role": "closing", "narration": "Mời bạn đọc.", "headline": "Mời bạn đọc"},
    ]
    (ctx.work / "script.json").write_text(json.dumps({"beats": beats}), encoding="utf-8")
    run_pipeline(ctx, RunOptions(from_stage="news_media"))
    plan = json.loads((ctx.output / "scene_plan.json").read_text(encoding="utf-8"))
    assert [r["layout"] for r in plan] == ["headline", "portrait_quote", "editorial_photo", "stat_card",
                                          "text_card", "timeline", "closing"]
    assert plan[4]["fallback"] and plan[-1]["end_sec"] > 15
