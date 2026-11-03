import json

import pytest
from PIL import Image

from studio.core.textnorm import clean_for_speech
from studio.pipeline.runner import RunOptions, run_pipeline
from studio.workflows import load_workflow, project_defaults
from studio.workflows.story_reader import passages, split_parts, story_sentences

from .conftest import make_project, needs_ffmpeg
from .test_workflows import POST

LONG_POST = "# Căn nhà cuối hẻm\nauthor: ke_ke_chuyen\ncommunity: TruyenMa\n\n" + "\n\n".join(
    f"Đêm thứ {i} tôi lại nghe tiếng gõ cửa. Tôi không dám mở. Tiếng gõ kéo dài đến tận sáng, rồi im bặt."
    for i in range(1, 13)
)


def _story_project(tmp_path, settings, name="p", text=POST, **options):
    d = project_defaults(load_workflow(settings, "story_reader"), "test_9x16")
    d["options"] = {**d["options"], "rewrite": "none", **options}
    ctx = make_project(tmp_path / name, settings, workflow="story_reader", **d)
    (ctx.dir / "source" / "source.md").write_text(text, encoding="utf-8")
    return ctx


def test_clean_for_speech():
    assert clean_for_speech("ko bt j hết 😂😂 xem https://x.com/a nha :))") == "không biết gì hết xem nha"
    assert clean_for_speech("Mn ơi, mình dc 5k #review @ban") == "mọi người ơi, mình được 5k review ban"
    assert clean_for_speech("A! Thật sao?") == "A! Thật sao?"  # capital interjection is not "anh"
    assert clean_for_speech("I am ok, a dog r us", lang="en") == "I am ok, a dog r us"  # shorthand is vi-only
    assert clean_for_speech("Đoạn một.\n\n\n Đoạn   hai.") == "Đoạn một.\n\nĐoạn hai."


def test_story_sentences_and_passages():
    s = story_sentences('Tôi bước tới mở cửa. "Ai ở ngoài đó?" Không. Không có ai cả! Chỉ có gió… Rồi đèn tắt.')
    assert s[0] == "Tôi bước tới mở cửa."
    assert s[1] == '"Ai ở ngoài đó?" Không.'  # closing quote kept; the tiny "Không." is glued to a neighbour
    assert s[-1] == "Không có ai cả! Chỉ có gió… Rồi đèn tắt."
    assert " ".join(s) == 'Tôi bước tới mở cửa. "Ai ở ngoài đó?" Không. Không có ai cả! Chỉ có gió… Rồi đèn tắt.'
    groups = passages(["Câu số một khá dài đây. Câu số hai cũng dài. Câu số ba dài nữa. Câu số bốn ở đây.",
                       "Đoạn mới bắt đầu."], max_chars=240)
    assert [len(g) for g in groups] == [3, 1, 1]  # max 3 sentences, never across segments


def test_split_parts_balanced():
    assert split_parts([10.0] * 5, 0) == [[0, 1, 2, 3, 4]]
    assert split_parts([10.0] * 5, 100) == [[0, 1, 2, 3, 4]]
    parts = split_parts([10.0] * 10, 45)  # 100 s into 45 s parts -> 3 parts of 30-40 s, no short tail
    assert len(parts) == 3 and [i for p in parts for i in p] == list(range(10))
    assert all(30 <= 10 * len(p) <= 45 for p in parts)
    assert split_parts([5.0, 80.0, 5.0], 40) == [[0], [1], [2]]  # an oversized item gets its own part


def test_passage_layout_scenes(tmp_path, settings):
    ctx = _story_project(tmp_path, settings, layout="passage")
    run_pipeline(ctx, RunOptions(only=["source", "script", "scenes"]))
    p = ctx.project
    ids = [s.scene_id for s in p.scenes]
    assert ids[0] == "s001_title" and ids[-1].endswith("_end")  # passthrough: hook == title -> no hook card
    body = p.scenes[1:-1]
    assert len(body) >= 5 and all(s.narration for s in body)
    for s in p.scenes:
        png = ctx.dir / s.visual.overlay
        assert png.is_file()
        w, h = Image.open(png).size
        assert w < ctx.fmt.width and h < ctx.fmt.height * 0.9
    assert p.video.subtitle_mode == "sidecar"
    assert p.scenes[-1].narration == p.options.get("cta", "Bạn nghĩ sao về câu chuyện này? Bình luận cho mình "
                                                          "biết nhé.")


def test_hook_card_when_hook_differs(tmp_path, settings):
    ctx = _story_project(tmp_path, settings, layout="passage")
    run_pipeline(ctx, RunOptions(only=["source", "script"]))
    sp = ctx.work / "script.json"
    script = json.loads(sp.read_text(encoding="utf-8"))
    script["hook"] = "Hai năm trời tôi không hề biết. Cho đến khi thấy hồ sơ tên Gấu."
    sp.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    run_pipeline(ctx, RunOptions(only=["scenes"]))
    first = ctx.project.scenes[0]
    assert first.scene_id == "s000_hook"
    assert Image.open(ctx.dir / first.visual.overlay).size == (ctx.fmt.width, ctx.fmt.height)


@pytest.mark.parametrize("layout", ["post", "passage"])
def test_parts_create_siblings(tmp_path, settings, layout):
    ctx = _story_project(tmp_path, settings, name="truyen", text=LONG_POST, layout=layout, part_max_sec=45)
    run_pipeline(ctx, RunOptions(only=["source", "script", "scenes"]))
    p = ctx.project
    n = p.options["parts"]
    assert n >= 2 and p.options["part"] == 1 and "Phần 1/" in p.title
    assert p.scenes[-1].narration == "Còn tiếp ở phần 2."
    sibs = sorted(tmp_path.glob("truyen_p*"))
    assert [s.name for s in sibs] == [f"truyen_p{k}" for k in range(2, n + 1)]
    last = json.loads((sibs[-1] / "project.json").read_text(encoding="utf-8"))
    assert last["options"]["part"] == n and last["options"]["part_of"] == "truyen"
    assert last["video"]["background"] == p.video.background
    assert last["scenes"][-1]["narration"] != f"Còn tiếp ở phần {n + 1}."
    # every sentence of the story is read exactly once across the parts
    spoken = [s.narration for s in p.scenes]
    for sib in sibs:
        spoken += [s["narration"] for s in json.loads((sib / "project.json").read_text(encoding="utf-8"))["scenes"]]
    assert sum(t.count("tiếng gõ cửa") for t in spoken) == 12
    # a sibling re-built with --force keeps its own part and makes no siblings of its own
    from studio.core.project import ProjectContext

    sctx = ProjectContext(sibs[0], settings=settings)
    run_pipeline(sctx, RunOptions(only=["scenes"], force=True))
    assert sctx.project.options["part"] == 2 and not list(tmp_path.glob("truyen_p2_p*"))


@needs_ffmpeg
@pytest.mark.ffmpeg
def test_passage_layout_end_to_end(tmp_path, settings):
    ctx = _story_project(tmp_path, settings, name="Truyện audio", layout="passage")
    run_pipeline(ctx, RunOptions())
    rep = json.loads((ctx.output / "qc_report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "PASS", rep
    assert (ctx.output / "captions.srt").is_file()
