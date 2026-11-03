import json

import pytest
from typer.testing import CliRunner

from studio.cli import app, slugify
from studio.core.errors import ManualGateRequired, ValidationError
from studio.pipeline.runner import RunOptions, run_pipeline
from studio.providers.llm import _strict_schema, extract_json, generate_json
from studio.workflows import list_workflows, load_workflow, project_defaults
from studio.workflows.story_reader import guess_lang, split_sentences

from .conftest import make_project, needs_ffmpeg

POST = """# Tôi phát hiện bạn cùng phòng dùng trộm Netflix của tôi suốt hai năm
url: https://www.reddit.com/r/test/comments/abc123/x/
author: nguoi_dung_1
community: TroChuyen
score: 1234

Chuyện là thế này. Hai năm trước tôi chia sẻ mật khẩu cho bạn cùng phòng. Sau đó chúng tôi chuyển nhà.

Tuần trước tôi thấy một hồ sơ lạ tên "Gấu" trong tài khoản. Hóa ra là cậu ấy! Tôi nên làm gì bây giờ?
"""


def test_workflow_recipes_load(settings):
    names = {w["name"]: w for w in list_workflows(settings)}
    assert names["story_reader"]["status"] == "ready"
    assert names["ai_cinematic"]["stages"][:2] == ["storyboard", "media"]
    d = project_defaults(load_workflow(settings, "story_reader"), "long_16x9")
    assert d["video"]["caption_style"] == "clean_box" and d["options"]["rewrite"] == "auto"


def test_helpers():
    assert slugify("Bí ẩn Kim tự tháp: Đáng sợ!") == "bi-an-kim-tu-thap-dang-so"
    assert guess_lang("Tôi phát hiện bạn cùng phòng") == "vi"
    assert guess_lang("I found out my roommate") == "en"
    chunks = split_sentences("Câu một. Câu hai dài hơn một chút. Câu ba!\n\nĐoạn mới.", 30)
    assert chunks[0] == "Câu một." and chunks[-1] == "Đoạn mới."
    assert all(len(c) <= 40 for c in chunks)


def test_story_reader_offline_stages(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, workflow="story_reader",
                       **project_defaults(load_workflow(settings, "story_reader"), "test_9x16"))
    (ctx.dir / "source" / "source.md").write_text(POST, encoding="utf-8")
    run_pipeline(ctx, RunOptions(only=["source", "script", "scenes"]))  # llm chain = manual -> passthrough
    src = json.loads((ctx.dir / "source" / "source.json").read_text(encoding="utf-8"))
    assert src["community"] == "TroChuyen" and src["score"] == 1234 and src["language"] == "vi"
    script = json.loads((ctx.work / "script.json").read_text(encoding="utf-8"))
    assert script["source"] == "passthrough"
    p = ctx.project
    assert p.scenes[0].scene_id == "s01_hook" and p.scenes[0].visual.overlay == "work/card.png"
    assert (ctx.dir / "work" / "card.png").is_file()
    assert p.scenes[-1].scene_id.endswith("_cta")
    assert p.source.credit_text and "TroChuyen" in p.source.credit_text
    assert p.video.background == "gradient" or p.video.background.startswith("asset:")
    # user edits are kept on re-run
    p.scenes[1].narration = "Đã sửa tay."
    ctx.save()
    run_pipeline(ctx, RunOptions(only=["source", "script", "scenes"]))
    assert ctx.project.scenes[1].narration == "Đã sửa tay."


def test_story_reader_translation_needs_llm(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, workflow="story_reader", language="vi",
                       options={"rewrite": "none"})
    (ctx.dir / "source" / "source.md").write_text("# My roommate\n\nI found out my roommate used my account.",
                                                  encoding="utf-8")
    with pytest.raises(ValidationError) as e:
        run_pipeline(ctx, RunOptions(only=["source", "script"]))
    assert e.value.code == "needs_llm"
    ctx.project.options["rewrite"] = "auto"
    with pytest.raises(ManualGateRequired):  # translation required, no CLI in the test chain
        run_pipeline(ctx, RunOptions(only=["script"]))
    todo = (ctx.dir / "TODO_MANUAL.md").read_text(encoding="utf-8")
    assert "work/llm/script.prompt.md" in todo
    assert (ctx.work / "llm" / "script.prompt.md").exists()


def test_source_gate_without_text(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, workflow="story_reader")
    with pytest.raises(ManualGateRequired) as e:
        run_pipeline(ctx, RunOptions())
    assert e.value.exit_code == 3
    assert ctx.stage_status("source") == "waiting_manual"


def test_llm_response_file_wins(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings)
    (ctx.work / "llm").mkdir()
    (ctx.work / "llm" / "t.response.json").write_text('{"a": 1}', encoding="utf-8")
    data, prov = generate_json(ctx, "t", "prompt", {"type": "object"}, chain=["claude_cli"])
    assert data == {"a": 1} and prov == "file"


def test_extract_json_and_strict_schema():
    assert extract_json('noise ```json\n{"x": [1, 2]}\n``` tail') == {"x": [1, 2]}
    assert extract_json('Answer: {"y": "z"} done') == {"y": "z"}
    s = _strict_schema({"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {}}}}})
    assert s["additionalProperties"] is False and s["required"] == ["a"]
    assert s["properties"]["a"]["required"] == ["b"]


def test_ai_cinematic_media_gate_and_still_fallback(tmp_path, settings):
    from .conftest import color_image

    ctx = make_project(tmp_path / "p", settings, workflow="ai_cinematic", timing_mode="fixed", scenes=[
        {"scene_id": "scene_01", "duration_sec": 4, "image_prompt": "a red fox", "video_prompt": "slow push in",
         "visual": {"type": "clip", "path": "clips/scene_01.mp4"}},
        {"scene_id": "scene_02", "duration_sec": 4, "image_prompt": "a blue lake",
         "visual": {"type": "clip", "path": "clips/scene_02.mp4"}},
    ])
    with pytest.raises(ManualGateRequired):
        run_pipeline(ctx, RunOptions(only=["storyboard", "media"]))
    todo = (ctx.dir / "TODO_MANUAL.md").read_text(encoding="utf-8")
    assert "a red fox" in todo and "clips/scene_02.mp4" in todo
    color_image(ctx.dir / "images" / "scene_01.png", (200, 50, 50))
    color_image(ctx.dir / "images" / "scene_02.jpg", (50, 50, 200))
    run_pipeline(ctx, RunOptions(only=["media"]))
    assert [s.visual.type for s in ctx.project.scenes] == ["still", "still"]


def test_cli_new_creates_projects(tmp_path, monkeypatch):
    src = tmp_path / "bài viết.md"
    src.write_text(POST, encoding="utf-8")
    target = tmp_path / "dự án mới"
    r = CliRunner().invoke(app, ["new", "story_reader", "Bạn cùng phòng", "--lang", "vi",
                                 "--text-file", str(src), "--format", "test_9x16", "--dir", str(target),
                                 "--set", "rewrite=none", "--set", "target_sec=45"])
    assert r.exit_code == 0, r.output
    pj = json.loads((target / "project.json").read_text(encoding="utf-8"))
    assert pj["workflow"] == "story_reader" and pj["video"]["format"] == "test_9x16"
    assert pj["options"]["rewrite"] == "none" and pj["options"]["target_sec"] == 45
    assert pj["options"]["card_theme"] == "light"  # recipe defaults kept
    assert pj["project_id"].endswith("ban-cung-phong")
    assert (target / "source" / "source.md").read_text(encoding="utf-8") == POST
    assert src.read_text(encoding="utf-8") == POST  # input untouched
    r2 = CliRunner().invoke(app, ["new", "story_reader", "x", "--dir", str(target)])
    assert r2.exit_code == 2  # refuses to overwrite an existing project


@needs_ffmpeg
@pytest.mark.ffmpeg
def test_story_reader_end_to_end(tmp_path, settings):
    ctx = make_project(tmp_path / "Câu chuyện 1", settings, workflow="story_reader",
                       **project_defaults(load_workflow(settings, "story_reader"), "test_9x16"))
    ctx.project.options["rewrite"] = "none"
    ctx.save()
    (ctx.dir / "source" / "source.md").write_text(POST, encoding="utf-8")
    run_pipeline(ctx, RunOptions())
    rep = json.loads((ctx.output / "qc_report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "PASS", rep
    tl = ctx.load_timeline()
    assert abs(rep["actual_duration_sec"] - tl["total_ms"] / 1000) <= 0.3
    assert not (ctx.dir / "TODO_MANUAL.md").exists()
    assert "Source" in (ctx.output / "metadata.md").read_text(encoding="utf-8")
