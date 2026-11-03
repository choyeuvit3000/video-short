"""Manim visual type, topic packs and the knowledge_explainer workflow."""

import json

import pytest
from typer.testing import CliRunner

from studio.cli import app
from studio.core.errors import ManualGateRequired, StudioError
from studio.core.validator import validate_project
from studio.pipeline.runner import RunOptions, run_pipeline
from studio.renderers.manim_render import (
    CUED_LIST,
    EXAMPLES,
    TEMPLATES,
    catalog,
    content_box,
    item_times,
    manim_available,
    validate_params,
)
from studio.workflows import load_workflow, project_defaults
from studio.workflows.topics import list_topics, load_topic

from .conftest import make_project, needs_ffmpeg

needs_manim = pytest.mark.skipif(not manim_available(), reason='manim not installed (uv pip install -e ".[manim]")')

SCRIPT = {
    "title": "Lãi kép", "description": "Vì sao nên bắt đầu sớm.", "hashtags": ["laikep"],
    "sources": [{"claim": "A = P(1+r)^n", "source": "Investopedia - Compound interest"}],
    "scenes": [
        {"narration": "Một trăm triệu gửi lãi năm phần trăm.", "template": "counter",
         "params": {"label": "Tiền gốc", "end": 100, "suffix": " triệu"}},
        {"narration": "Bí quyết là bắt đầu sớm và kiên nhẫn.", "template": "bullets",
         "params": json.dumps({"items": [{"text": "Bắt đầu sớm", "cue": "bắt"}, {"text": "Kiên nhẫn", "cue": "kiên"}]},
                              ensure_ascii=False)},
        {"narration": "Cảnh này có tham số sai.", "template": "bar_chart", "params": {"bars": [], "color": "red"}},
    ],
}


def _explainer_project(tmp_path, settings, script=SCRIPT, **options):
    defaults = project_defaults(load_workflow(settings, "knowledge_explainer"), "test_9x16")
    ctx = make_project(tmp_path / "Kiến thức 1", settings, workflow="knowledge_explainer", **defaults)
    ctx.project.options.update({"topic": "finance", "brief": "Lãi kép là gì", **options})
    ctx.save()
    llm = ctx.work / "llm"
    llm.mkdir(parents=True, exist_ok=True)
    (llm / "explainer.response.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    return ctx


def test_every_template_example_validates_and_bad_params_fail():
    assert set(EXAMPLES) == set(TEMPLATES)
    for name, params in EXAMPLES.items():
        assert validate_params(name, params)
    assert "`function_graph`" in catalog() and "example params" in catalog(["title"])
    for name, params, code in [
        ("nope", {}, "unknown_manim_template"),
        ("bullets", {"items": []}, "bad_manim_params"),
        ("bullets", {"items": [{"text": "a"}], "extra": 1}, "bad_manim_params"),  # extra keys refused
        ("bar_chart", {"bars": [{"label": "a", "value": 1}, {"label": "b", "value": 2}], "highlight": 5},
         "bad_manim_params"),
        ("line_chart", {"x_labels": ["a", "b"], "series": [{"name": "s", "values": [1, 2, 3]}]}, "bad_manim_params"),
        ("function_graph", {"curves": [{"kind": "normal", "a": 0}]}, "bad_manim_params"),
        ("function_graph", {"curves": [{"kind": "exec", "a": 1}]}, "bad_manim_params"),
    ]:
        with pytest.raises(StudioError) as e:
            validate_params(name, params)
        assert e.value.code == code, (name, params)


def test_item_times_follow_cue_words_in_order():
    words = [{"text": w, "start_ms": i * 500, "end_ms": i * 500 + 400}
             for i, w in enumerate("Đầu tiên là nắng sau đó là Mưa rồi lại nắng".split())]
    t = item_times(["nắng", "mưa", "nắng"], words, 6.0)
    assert t == [1.5, 3.5, 5.0]  # second "nắng" resolves after "mưa"; case and diacritics normalised
    even = item_times([None, None, "không-có"], words, 6.0)
    assert even[0] == 0.6 and even[0] < even[1] < even[2]
    close = item_times(["là", "là"], words, 6.0)
    assert close[1] - close[0] >= 0.25
    assert item_times([], words, 3) == []


@pytest.mark.parametrize("fmt", ["short_9x16", "long_16x9", "test_9x16"])
def test_content_box_inside_safe_zone_and_above_captions(settings, fmt):
    from studio.renderers.render import caption_box

    f = settings.format(fmt)
    box = content_box(f, captions=True)
    safe = f.safe_zone or {}
    assert 0 <= box["x0"] < box["x1"] <= f.width and 0 <= box["y0"] < box["y1"] <= f.height
    assert box["y0"] >= safe.get("top", 0) and box["x1"] <= f.width - safe.get("right", 0)
    cap = caption_box(f)
    if f.height > 1000:  # real formats: two caption lines fit under the box
        assert box["y1"] <= f.height - cap["margin_v"] - 2 * cap["font_size"]
    assert content_box(f, captions=False)["y1"] >= box["y1"]


def test_topic_packs(settings):
    topics = {t.id: t for t in list_topics(settings)}
    assert {"science", "history", "finance", "math", "technology", "geography", "psychology", "health"} <= set(topics)
    fin = topics["finance"]
    assert "lời khuyên đầu tư" in fin.disclaimer_for("vi") and "financial advice" in fin.disclaimer_for("en")
    assert fin.disclaimer_on_screen and fin.require_sources and fin.review_required
    assert topics["health"].disclaimer_for("vi")
    for t in topics.values():
        assert set(t.templates) <= set(TEMPLATES) and t.label("vi") and t.hashtags.get("vi")
    with pytest.raises(StudioError) as e:
        load_topic(settings, "astrology")
    assert e.value.code == "unknown_topic"


def test_explainer_writes_scenes_then_waits_for_review(tmp_path, settings):
    ctx = _explainer_project(tmp_path, settings)
    with pytest.raises(ManualGateRequired) as e:
        run_pipeline(ctx, RunOptions(only=["explainer", "review"]))
    assert e.value.stage == "review"
    p = ctx.project
    assert [s.visual.template for s in p.scenes] == ["counter", "bullets", "title"]  # bad scene -> title card
    assert p.scenes[1].visual.params["items"][0]["cue"] == "bắt"  # params given as a JSON string are accepted
    assert all(s.visual.type == "manim" for s in p.scenes)
    assert "không phải lời khuyên đầu tư" in p.description
    assert p.options["on_screen_note"] and p.options["palette"]["background"]
    assert "#laikep" in p.hashtags and "#taichinh" in p.hashtags
    assert p.options["sources"][0]["source"].startswith("Investopedia")
    todo = (ctx.dir / "TODO_MANUAL.md").read_text(encoding="utf-8")
    assert "studio approve" in todo and "Investopedia" in todo and "guaranteed" in todo

    r = CliRunner().invoke(app, ["approve", str(ctx.dir)])
    assert r.exit_code == 0, r.output
    ctx2 = type(ctx)(ctx.dir, settings=settings)
    run_pipeline(ctx2, RunOptions(only=["explainer", "review"]))  # scenes kept, review passes
    assert [s.visual.template for s in ctx2.project.scenes] == ["counter", "bullets", "title"]

    ctx2.project.scenes = []  # a new script needs a new review
    ctx2.save()
    run_pipeline(ctx2, RunOptions(only=["explainer"]))
    assert len(ctx2.project.scenes) == 3 and ctx2.project.options["reviewed"] is False


def test_explainer_drops_bracket_notes_from_narration(tmp_path, settings):
    script = json.loads(json.dumps(SCRIPT))
    script["scenes"][0]["narration"] = "Quân Nam Hán [Southern Han]  kéo sang [Lưu Hoằng Tháo]."
    ctx = _explainer_project(tmp_path, settings, script=script)
    run_pipeline(ctx, RunOptions(only=["explainer"]))
    assert ctx.project.scenes[0].narration == "Quân Nam Hán kéo sang."
    assert ctx.project.scenes[1].narration == SCRIPT["scenes"][1]["narration"]


def test_explainer_drops_word_notes_from_on_screen_text(tmp_path, settings):
    script = json.loads(json.dumps(SCRIPT))
    script["scenes"][0]["params"] = {"label": "Ái Châu [Thanh Hóa] tiến quân", "end": 100,
                                     "note": "khoảng [0, 10] năm"}
    script["scenes"][1]["params"] = json.dumps({"items": [{"text": "Nam Hán [Southern Han]"}]}, ensure_ascii=False)
    ctx = _explainer_project(tmp_path, settings, script=script)
    run_pipeline(ctx, RunOptions(only=["explainer"]))
    s1, s2 = (sc.visual.params for sc in ctx.project.scenes[:2])
    assert s1["label"] == "Ái Châu tiến quân" and s1["note"] == "khoảng [0, 10] năm"  # an interval stays
    assert s2["items"][0]["text"] == "Nam Hán"


def test_explainer_without_brief_waits(tmp_path, settings):
    ctx = _explainer_project(tmp_path, settings, brief="")
    with pytest.raises(ManualGateRequired) as e:
        run_pipeline(ctx, RunOptions(only=["explainer"]))
    assert e.value.stage == "explainer"


def test_validator_checks_manim_scenes(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, scenes=[
        {"scene_id": "s1", "visual": {"type": "manim"}},
        {"scene_id": "s2", "visual": {"type": "manim", "template": "bullets", "params": {"items": []}}},
        {"scene_id": "s3", "visual": {"type": "manim", "file": "manim/missing.py", "scene_class": "X"}},
        {"scene_id": "s4", "visual": {"type": "manim", "file": "manim/scene.txt", "scene_class": "X"}},
        {"scene_id": "s5", "visual": {"type": "manim", "file": "../outside.py", "scene_class": "X"}},
        {"scene_id": "s6", "visual": {"type": "manim", "template": "title", "params": {"title": "OK"}}},
    ])
    codes = {(i.scene_id, i.code) for i in validate_project(ctx) if i.level == "error"}
    assert {("s1", "schema_error"), ("s2", "bad_manim_params"), ("s3", "missing_manim_file"),
            ("s4", "bad_manim_params"), ("s5", "path_traversal")} <= codes
    assert not any(sid == "s6" for sid, c in codes if c != "manim_missing")


def test_cli_new_with_topic_and_topics_list(tmp_path):
    target = tmp_path / "lịch sử"
    r = CliRunner().invoke(app, ["new", "knowledge_explainer", "Bạch Đằng", "--topic", "history",
                                 "--brief", "Trận Bạch Đằng 938", "--format", "test_9x16", "--dir", str(target)])
    assert r.exit_code == 0, r.output
    pj = json.loads((target / "project.json").read_text(encoding="utf-8"))
    assert pj["options"]["topic"] == "history" and pj["options"]["brief"] == "Trận Bạch Đằng 938"
    assert pj["options"]["palette"]["background"] == "#1A1410" and pj["video"]["caption_style"] == "clean_box"
    assert "on_screen_note" not in pj["options"]  # history has no disclaimer
    bad = CliRunner().invoke(app, ["new", "knowledge_explainer", "x", "--topic", "nope", "--dir",
                                   str(tmp_path / "x")])
    assert bad.exit_code == 2
    lst = CliRunner().invoke(app, ["topics"])
    assert lst.exit_code == 0 and "finance" in lst.output


@needs_ffmpeg
@needs_manim
@pytest.mark.ffmpeg
def test_knowledge_explainer_renders_with_manim(tmp_path, settings):
    script = {**SCRIPT, "scenes": SCRIPT["scenes"][:2]}
    ctx = _explainer_project(tmp_path, settings, script=script, reviewed=True)
    run_pipeline(ctx, RunOptions(only=["explainer"]))
    ctx.project.options["reviewed"] = True
    ctx.save()
    stages = ["review", "validate", "voice", "render", "qc", "package"]
    run_pipeline(ctx, RunOptions(only=stages))
    rep = json.loads((ctx.output / "qc_report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "PASS" and rep["warnings"] == [], rep
    spec = json.loads((ctx.work / "manim" / "scene_02.spec.json").read_text(encoding="utf-8"))
    assert spec["template"] == "bullets" and len(spec["times"]) == 2 and spec["times"][0] < spec["times"][1]
    assert spec["footer"] is None and json.loads(
        (ctx.work / "manim" / "scene_01.spec.json").read_text(encoding="utf-8"))["footer"]
    meta = (ctx.output / "metadata.md").read_text(encoding="utf-8")
    assert "## Sources" in meta and "Investopedia" in meta
    anim = {p.name: p.stat().st_mtime_ns for p in (ctx.work / "manim").glob("*.mp4")}
    assert set(anim) == {"scene_01.mp4", "scene_02.mp4"}

    run_pipeline(ctx, RunOptions(only=stages))  # unchanged -> skipped
    st = json.loads((ctx.dir / "state.json").read_text(encoding="utf-8"))["stages"]
    assert st["render"].get("skipped"), st

    ctx.project.scenes[0].visual.params["end"] = 200  # only that animation is rebuilt
    ctx.save()
    run_pipeline(ctx, RunOptions(only=stages))
    after = {p.name: p.stat().st_mtime_ns for p in (ctx.work / "manim").glob("*.mp4")}
    assert after["scene_01.mp4"] != anim["scene_01.mp4"] and after["scene_02.mp4"] == anim["scene_02.mp4"]


@needs_ffmpeg
@needs_manim
@pytest.mark.ffmpeg
def test_custom_manim_scene_file(tmp_path, settings):
    ctx = make_project(tmp_path / "tùy chỉnh", settings, video={"subtitle_mode": "none"}, scenes=[
        {"scene_id": "scene_01", "duration_sec": 2,
         "visual": {"type": "manim", "file": "manim/my scene.py", "scene_class": "Dot2"}},
    ])
    (ctx.dir / "manim").mkdir()
    (ctx.dir / "manim" / "my scene.py").write_text(
        "from manim import *\n\nclass Dot2(Scene):\n    def construct(self):\n"
        "        self.play(Create(Circle(color=YELLOW)), run_time=1)\n        self.wait(1)\n", encoding="utf-8")
    issues = validate_project(ctx)
    assert any(i.code == "custom_code" and i.level == "warning" for i in issues)
    assert not [i for i in issues if i.level == "error"]
    run_pipeline(ctx, RunOptions(only=["validate", "voice", "render", "qc"]))
    rep = json.loads((ctx.output / "qc_report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "PASS", rep
    assert (ctx.work / "manim" / "scene_01.mp4").is_file()
    assert (ctx.dir / "manim" / "my scene.py").is_file()  # user file untouched


def test_cued_list_keys_exist_in_params():
    for template, key in CUED_LIST.items():
        assert key in TEMPLATES[template].model_fields
