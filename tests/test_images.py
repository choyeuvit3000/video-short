"""Real photos (Wikimedia Commons, mocked HTTP), voice speed and centred layout boxes."""

import io
import json

import httpx
import pytest

from studio.core.errors import ManualGateRequired, ProviderUnavailable
from studio.core.validator import validate_project
from studio.pipeline.runner import RunOptions, run_pipeline
from studio.providers import images
from studio.renderers.manim_render import content_box, manim_available
from studio.renderers.render import caption_box
from studio.voices import VoiceProfile, with_speed

from .conftest import color_image, make_project, needs_ffmpeg
from .test_manim import SCRIPT, _explainer_project

needs_manim = pytest.mark.skipif(not manim_available(), reason="manim not installed")


def _page(i, title, lic="CC BY-SA 4.0", w=2000, h=1500, mime="image/jpeg", desc="", nonfree="false"):
    return {"index": i, "title": f"File:{title}", "imageinfo": [{
        "url": f"https://upload.example/{i}.jpg", "thumburl": f"https://upload.example/{i}_1600.jpg",
        "descriptionurl": f"https://commons.example/wiki/File:{i}", "width": w, "height": h, "mime": mime,
        "extmetadata": {"LicenseShortName": {"value": lic}, "Artist": {"value": "<a href='x'>Nguyễn A</a>"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                        "ImageDescription": {"value": desc}, "NonFree": {"value": nonfree}}}]}


PAGES = [
    _page(1, "Pluto map.jpg", desc="dwarf planet"),                       # no shared word -> dropped
    _page(2, "Bach Dang stakes.jpg", lic="All rights reserved"),          # not free -> dropped
    _page(3, "Bach Dang small.jpg", w=300, h=200),                        # too small -> dropped
    _page(4, "Bach Dang fair use.jpg", nonfree="true"),                   # non-free flag -> dropped
    _page(5, "River landscape.jpg", lic="Public domain", desc="the Bach Dang river"),  # description match
    _page(6, "Bach Dang river 2019.jpg", lic="CC0"),                      # title match -> first
    _page(7, "Bach Dang map.svg", mime="image/svg+xml", w=512, h=400),    # svg kept (rendered to png)
]


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _client(calls, pages=PAGES, body=None):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.host == "commons.wikimedia.org":
            assert req.headers["user-agent"].startswith("video-short-studio")
            return httpx.Response(200, json={"query": {"pages": pages}})
        return httpx.Response(200, content=body if body is not None else _png())
    return httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": images.UA})


def test_search_keeps_free_relevant_files_best_first():
    found = images.search_commons("Bach Dang river", client=_client([]))
    # score: 2 x title words + description words shared with the query
    assert [p.title for p in found] == ["File:Bach Dang river 2019.jpg", "File:River landscape.jpg",
                                        "File:Bach Dang map.svg"]
    top = found[0]
    assert top.author == "Nguyễn A" and top.url.endswith("_1600.jpg") and top.license == "CC0"
    assert top.credit() == "Ảnh: Nguyễn A · CC0 · Wikimedia Commons"
    assert images.is_free("CC BY 2.0") and images.is_free("PD-old") and not images.is_free("CC BY-NC 4.0")
    assert images._words("Ngô Quyền, Đại Việt") == {"ngo", "quyen", "dai", "viet"}
    assert images._author("<span>Unknown author</span> <span>Unknown author</span>") == "không rõ tác giả"
    assert images._author("<a>Herbert Ponting</a> Herbert Ponting") == "Herbert Ponting"
    assert images._author("Lê Văn A") == "Lê Văn A" and images._author("") == "không rõ tác giả"


def test_find_photo_downloads_once_then_uses_the_cache(tmp_path):
    calls: list[str] = []
    dest = tmp_path / "p" / "work" / "images"
    dest.mkdir(parents=True)
    path, photo = images.find_photo(tmp_path / "cache", "Bach Dang river", dest / "scene_01", client=_client(calls))
    assert path.name == "scene_01.jpg" and path.read_bytes() == _png() and photo.license == "CC0"
    assert not list(dest.glob("*.part"))
    n = len(calls)
    again, _ = images.find_photo(tmp_path / "cache", "bach dang river ", dest / "scene_02", client=_client(calls))
    assert len(calls) == n and again.read_bytes() == _png()  # search + file both from cache
    other, ph2 = images.find_photo(tmp_path / "cache", "Bach Dang river", dest / "scene_03",
                                   avoid={photo.title, "File:River landscape.jpg"}, client=_client(calls))
    assert ph2.title != photo.title and other.suffix == ".png"  # the svg, as a png thumbnail


def test_long_queries_are_shortened_until_something_is_found(tmp_path):
    assert images._relaxed("a b c d") == ["a b c d", "a b c", "a b"]
    assert images._relaxed("Hubble") == ["Hubble"]
    asked = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host != "commons.wikimedia.org":
            return httpx.Response(200, content=_png())
        q = req.url.params["gsrsearch"]
        asked.append(q)
        return httpx.Response(200, json={"query": {"pages": PAGES if len(q.split()) <= 3 else []}})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    _, photo = images.find_photo(tmp_path / "c", "Bach Dang river estuary 938", tmp_path / "x", client=client)
    assert asked == ["Bach Dang river estuary 938", "Bach Dang river estuary", "Bach Dang river"]
    assert photo.title == "File:Bach Dang river 2019.jpg"


def test_bad_download_and_offline_raise(tmp_path):
    photo = images.search_commons("Bach Dang river", client=_client([]))[0]
    with pytest.raises(ProviderUnavailable) as e:
        images.download(photo, tmp_path / "x", client=_client([], body=b"<html>not an image</html>"))
    assert e.value.code == "images_offline" and not list(tmp_path.iterdir())

    def down(req):
        raise httpx.ConnectError("offline", request=req)
    with pytest.raises(ProviderUnavailable):
        images.search_commons("x y z", client=httpx.Client(transport=httpx.MockTransport(down)))


PHOTO_SCRIPT = {**SCRIPT, "scenes": [
    SCRIPT["scenes"][0],
    {"narration": "Đây là sông Bạch Đằng.", "template": "photo",
     "params": {"query": "Bach Dang river", "caption": "Sông Bạch Đằng"}},
    {"narration": "Không có ảnh nào khớp.", "template": "photo", "params": {"query": "zzz nothing", "caption": "X"}},
]}


def test_images_stage_sets_file_credit_and_falls_back(tmp_path, settings, monkeypatch):
    ctx = _explainer_project(tmp_path, settings, script=PHOTO_SCRIPT)
    run_pipeline(ctx, RunOptions(only=["explainer"]))
    prompt = (ctx.work / "llm" / "explainer.prompt.md").read_text(encoding="utf-8")
    assert "`photo`" in prompt and "for 2 scene(s)" in prompt
    issues = {(i.scene_id, i.code) for i in validate_project(ctx)}
    assert ("scene_02", "missing_photo") in issues  # validator refuses a photo scene without a file

    def fake(cache_root, query, stem, *, avoid=frozenset(), client=None):
        if query.startswith("zzz"):
            return None
        path = color_image(stem.with_suffix(".jpg"), (0, 90, 160))
        return path, images.Photo("File:Bach Dang.jpg", "u", "https://commons.example/p", "Tác giả", "CC BY 4.0",
                                  "https://creativecommons.org/licenses/by/4.0", 800, 600, "image/jpeg")
    monkeypatch.setattr(images, "find_photo", fake)
    with pytest.raises(ManualGateRequired):
        run_pipeline(ctx, RunOptions(only=["images", "review"]))
    s2, s3 = ctx.project.scenes[1].visual, ctx.project.scenes[2].visual
    assert s2.template == "photo" and s2.params["file"] == "work/images/scene_02.jpg"
    assert s2.params["credit"] == "Ảnh: Tác giả · CC BY 4.0 · Wikimedia Commons"
    assert s3.template == "title" and s3.params["title"] == "X"
    cred = ctx.project.options["image_credits"]
    assert [c["scene_id"] for c in cred] == ["scene_02"] and cred[0]["page"] == "https://commons.example/p"
    todo = (ctx.dir / "TODO_MANUAL.md").read_text(encoding="utf-8")
    assert "work/images/scene_02.jpg" in todo and "each photo shows what" in todo
    assert not any(c == "missing_photo" for _, c in {(i.scene_id, i.code) for i in validate_project(ctx)})

    monkeypatch.setattr(images, "find_photo", lambda *a, **k: pytest.fail("photo kept -> no new search"))
    run_pipeline(ctx, RunOptions(only=["images"]))


def test_with_speed_per_provider():
    def prof(provider, **params):
        return VoiceProfile(id="v", lang="vi", tier="free", provider=provider, params=params)
    assert with_speed(prof("edge", rate="+0%"), 1.25).params["rate"] == "+25%"
    assert with_speed(prof("edge", rate="+5%"), 1.25).params["rate"] == "+31%"
    assert with_speed(prof("edge"), 0.8).params["rate"] == "-20%"
    assert with_speed(prof("piper", length_scale=1.0), 1.25).params["length_scale"] == 0.8
    assert with_speed(prof("mock", chars_per_sec=14), 1.25).params["chars_per_sec"] == 17.5
    assert with_speed(prof("xtts"), 1.25).params["speed"] == 1.25
    p = prof("edge", rate="+0%")
    assert with_speed(p, 1.0) is p and p.params["rate"] == "+0%"  # original untouched


def test_speed_shortens_the_voice(tmp_path, settings):
    durs = []
    for speed in (1.0, 1.25):
        ctx = make_project(tmp_path / f"s{speed}", settings, audio={"voice_profile": "mock-vi", "speed": speed},
                           scenes=[{"scene_id": "s1", "narration": "Một câu khá dài để đo tốc độ đọc của giọng."}])
        run_pipeline(ctx, RunOptions(only=["voice"]))
        durs.append(ctx.load_timeline()["scenes"][0]["voice_ms"])
    assert durs[1] < durs[0] * 0.85


@pytest.mark.parametrize("fmt", ["short_9x16", "long_16x9", "square_1x1"])
def test_boxes_are_horizontally_centred(settings, fmt):
    f = settings.format(fmt)
    box = content_box(f, captions=True)
    assert box["x0"] == f.width - box["x1"]
    cap = caption_box(f)
    assert cap["margin_l"] == cap["margin_r"] >= max((f.safe_zone or {}).get("right", 0),
                                                    (f.safe_zone or {}).get("left", 0))


@needs_ffmpeg
@needs_manim
@pytest.mark.ffmpeg
def test_photo_scene_renders(tmp_path, settings):
    ctx = _explainer_project(tmp_path, settings, script={**PHOTO_SCRIPT, "scenes": PHOTO_SCRIPT["scenes"][1:2]})
    run_pipeline(ctx, RunOptions(only=["explainer"]))
    color_image(ctx.work / "images" / "mine.jpg", (200, 80, 40), size=(1200, 800))
    v = ctx.project.scenes[0].visual
    v.params = {**v.params, "file": "work/images/mine.jpg", "credit": "Ảnh: tôi · CC0 · Wikimedia Commons"}
    ctx.project.options["reviewed"] = True
    ctx.save()
    run_pipeline(ctx, RunOptions(only=["images", "review", "validate", "voice", "render", "qc", "package"]))
    rep = json.loads((ctx.output / "qc_report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "PASS", rep
    spec = json.loads((ctx.work / "manim" / "scene_01.spec.json").read_text(encoding="utf-8"))
    assert spec["image"].endswith("mine.jpg") and spec["image_sha"]
