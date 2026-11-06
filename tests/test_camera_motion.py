import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from studio.core.errors import ManualGateRequired
from studio.social_video import illustrated_full
from studio.social_video.camera_motion import camera_affine, sample_frame, zoom_at
from studio.social_video.illustrated_full import frozen_motion_inputs, motion_repair_authorization
from studio.social_video.quality import sha256


def test_zoom_has_exact_extent_monotonic_motion_and_soft_endpoints():
    values = [zoom_at(i, 301) for i in range(301)]
    assert values[0] == 1
    assert values[-1] == 1.045
    assert all(a <= b for a, b in zip(values, values[1:], strict=False))
    assert values[1] - values[0] < 1e-7
    assert values[-1] - values[-2] < 1e-7
    assert zoom_at(0, 301, zoom_in=False) == 1.045
    assert zoom_at(300, 301, zoom_in=False) == 1


@pytest.mark.parametrize("crop,center", [
    (None, (836, 470.5)),
    ({"x": 620, "y": 260, "w": 1024, "h": 576}, (1132, 548)),
    ({"x": 2000, "y": -20, "w": 1024, "h": 576}, (1160, 288)),
])
def test_focal_point_never_moves_when_scale_changes(crop, center):
    for i in range(0, 301, 7):
        a, b, c, d, e, f = camera_affine((1672, 941), i, 301, crop=crop)
        assert a * 960 + b * 540 + c == pytest.approx(center[0], abs=1e-10)
        assert d * 960 + e * 540 + f == pytest.approx(center[1], abs=1e-10)


def test_actual_resampling_keeps_a_centered_marker_stationary():
    image = Image.new("RGB", (160, 90), "white")
    ImageDraw.Draw(image).ellipse((73, 38, 86, 51), fill="black")
    centers = []
    for i in range(0, 301, 3):
        frame = sample_frame(image, i, 301, output_size=(320, 180))
        weight = 255 - np.asarray(frame, dtype=float).mean(axis=2)
        yy, xx = np.indices(weight.shape)
        centers.append(((xx * weight).sum() / weight.sum(), (yy * weight).sum() / weight.sum()))
        assert np.asarray(frame)[0].min() == 255  # no exposed outer edge
    centers = np.asarray(centers)
    assert np.ptp(centers, axis=0).max() < .025


def test_stabilization_fingerprint_rejects_changed_camera_framing():
    plan = {"script_sha256": "script", "source_voice_review_fingerprint": "voice",
            "source_video_sha256": "audio", "duration_seconds": 10, "style_selected": "A",
            "shots": [{"asset_key": "boat", "start_seconds": 0, "end_seconds": 10}]}
    before = frozen_motion_inputs(plan)
    plan["status"] = "technical correction"
    assert frozen_motion_inputs(plan) == before
    plan["shots"][0]["crop"] = {"x": 10, "y": 0, "w": 900, "h": 500}
    assert frozen_motion_inputs(plan) != before


def test_invalid_frame_is_rejected():
    with pytest.raises(ValueError):
        zoom_at(30, 30)


@pytest.fixture
def repair_case(tmp_path, monkeypatch):
    plan = {"script_sha256": "script", "source_voice_review_fingerprint": "voice",
            "source_video_sha256": "audio", "duration_seconds": 10, "style_selected": "A",
            "shots": [{"asset_key": "boat", "start_seconds": 0, "end_seconds": 10}]}
    baseline = tmp_path / "accepted_plan.json"
    baseline.write_text(json.dumps(plan), encoding="utf-8")
    manifest = tmp_path / "image_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    approved = tmp_path / "accepted.mp4"
    output = tmp_path / "stable.mp4"
    monkeypatch.setattr(illustrated_full, "require", lambda folder, stage: {"fingerprint": "accepted"})
    monkeypatch.setattr(illustrated_full, "payload", lambda folder, stage: {
        "videos": [{"path": str(approved), "sha256": "accepted-video"}]})
    auth = {"message": "Sửa rung zoom", "allowed_changes": ["camera_motion"],
            "approved_fingerprint": "accepted", "approved_video_path": str(approved),
            "approved_video_sha256": "accepted-video", "output_path": str(output),
            "approved_plan_path": str(baseline), "approved_plan_sha256": sha256(baseline),
            "image_manifest_sha256": sha256(manifest)}
    return plan, auth, approved, output


def test_post_approval_fix_preserves_accepted_result_and_requires_scoped_request(tmp_path, repair_case):
    plan, auth, approved, output = repair_case
    with pytest.raises(ManualGateRequired):
        motion_repair_authorization(tmp_path, plan, tmp_path, output)
    file = tmp_path / "technical_repair_authorization.json"
    file.write_text(json.dumps(auth), encoding="utf-8")
    assert motion_repair_authorization(tmp_path, plan, tmp_path, output)["message"] == "Sửa rung zoom"
    auth["output_path"] = str(approved)
    file.write_text(json.dumps(auth), encoding="utf-8")
    with pytest.raises(ValueError, match="Preserve the accepted"):
        motion_repair_authorization(tmp_path, plan, tmp_path, approved)


def test_motion_authorization_cannot_change_narration(tmp_path, repair_case):
    plan, auth, _approved, output = repair_case
    (tmp_path / "technical_repair_authorization.json").write_text(json.dumps(auth), encoding="utf-8")
    plan["source_voice_review_fingerprint"] = "another voice"
    with pytest.raises(ValueError, match="cannot change content"):
        motion_repair_authorization(tmp_path, plan, tmp_path, output)
