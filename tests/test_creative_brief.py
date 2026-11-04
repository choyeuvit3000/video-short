import json

import pytest

from studio.core.creative_brief import approve, ensure_ready, finish_render, prepare, reserve_render
from studio.core.errors import ManualGateRequired, ValidationError


def test_approval_invalidation_and_render_budget(tmp_path):
    source = tmp_path / "posts.json"
    source.write_text("[]")
    assert prepare(tmp_path)["missing"] == ["goal", "audience"]
    with pytest.raises(ManualGateRequired):
        ensure_ready(tmp_path)
    prepare(tmp_path, {"goal": "Review source", "audience": "Vietnamese viewer"})
    approve(tmp_path, "creator")
    reserve_render(tmp_path, "first")
    finish_render(tmp_path, False)
    assert json.loads((tmp_path / "generation_budget.json").read_text())["attempts"][0]["status"] == "FAILED"
    approve(tmp_path, "creator")
    with pytest.raises(ManualGateRequired):
        reserve_render(tmp_path, "second")
    source.write_text('[{"part_texts":["changed"]}]')
    assert prepare(tmp_path)["status"] == "DRAFT"
    with pytest.raises(ManualGateRequired):
        ensure_ready(tmp_path)


@pytest.mark.parametrize("voice", ["edge-vi-NamMinh", "vieneu-vi-maianh"])
def test_brief_rejects_blacklist(tmp_path, voice):
    (tmp_path / "posts.json").write_text("[]")
    with pytest.raises(ValidationError):
        prepare(tmp_path, {"voice": voice})


def test_new_brief_uses_machine_voice_default(tmp_path, monkeypatch):
    from types import SimpleNamespace

    (tmp_path / "posts.json").write_text("[]")
    monkeypatch.setattr(
        "studio.voices.load_registry", lambda settings: SimpleNamespace(defaults={"vi": "omnivoice-vi-thaison"})
    )
    assert prepare(tmp_path)["answers"]["voice"] == "omnivoice-vi-thaison"
