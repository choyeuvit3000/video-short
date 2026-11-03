import pytest
from pydantic import ValidationError as PydanticValidationError

from studio.core.errors import ValidationError
from studio.core.paths import resolve_inside
from studio.core.project import load_project
from studio.core.schema import Project


def test_minimal_project_defaults():
    p = Project.model_validate({"project_id": "abc"})
    assert p.schema_version == "2.0"
    assert p.timing_mode == "audio_driven"
    assert p.video.format == "short_9x16"
    assert p.budget.max_cost_usd == 0


def test_duplicate_scene_ids_rejected():
    with pytest.raises(PydanticValidationError, match="duplicate scene_id"):
        Project.model_validate({"project_id": "a", "scenes": [{"scene_id": "s1"}, {"scene_id": "s1"}]})


@pytest.mark.parametrize("bad", ["../evil", "a/b", "", "x" * 65, "có dấu"])
def test_bad_scene_id(bad):
    with pytest.raises(PydanticValidationError):
        Project.model_validate({"project_id": "a", "scenes": [{"scene_id": bad}]})


def test_fixed_timing_requires_duration():
    with pytest.raises(PydanticValidationError, match="duration_sec is required"):
        Project.model_validate({"project_id": "a", "timing_mode": "fixed", "scenes": [{"scene_id": "s1"}]})


def test_v1_upgrade():
    v1 = {
        "schema_version": "1.0", "project_id": "demo", "language": "vi-VN",
        "video": {"width": 1080, "height": 1920, "fps": 30, "subtitle_mode": "burn_in"},
        "audio": {"source": "tts", "voice": "vi-VN-HoaiMyNeural"},
        "scenes": [{"scene_id": "scene_01", "duration_sec": 8, "narration": "x",
                    "video_path": "clips/scene_01.mp4"},
                   {"scene_id": "scene_02", "duration_sec": 6, "image_path": "images/scene_02.png"}],
    }
    p = Project.model_validate(v1)
    assert p.timing_mode == "fixed" and p.language == "vi"
    assert p.video.format == "short_9x16"
    assert p.scenes[0].visual.type == "clip" and p.scenes[0].visual.path == "clips/scene_01.mp4"
    assert p.scenes[1].visual.type == "still"
    assert p.options["v1_edge_voice"] == "vi-VN-HoaiMyNeural"


@pytest.mark.parametrize("ref", ["../outside.mp4", "clips/../../x.mp4", "C:/Windows/win.ini", "/etc/passwd"])
def test_path_traversal_refused(tmp_path, ref):
    with pytest.raises(ValidationError):
        resolve_inside(tmp_path, ref)


def test_resolve_inside_ok(tmp_path):
    assert resolve_inside(tmp_path, "clips/a b/ảnh.png") == (tmp_path / "clips" / "a b" / "ảnh.png").resolve()


def test_load_project_errors(tmp_path):
    with pytest.raises(ValidationError) as e:
        load_project(tmp_path / "project.json")
    assert e.value.code == "missing_project"
    (tmp_path / "project.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValidationError) as e:
        load_project(tmp_path / "project.json")
    assert e.value.code == "schema_error"
