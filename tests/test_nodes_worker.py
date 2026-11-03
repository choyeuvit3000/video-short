"""M3.5 multi-machine: schedules, node selection, worker API security, submit -> run -> pull round trip.

The worker runs in-process through FastAPI's TestClient; no network, no real GPU.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from studio.core.config import Settings, deep_merge  # noqa: E402
from studio.core.errors import EXIT_WAITING_NODE, ProviderUnavailable, WaitingForNode  # noqa: E402
from studio.nodes import DAYS, NodeUnavailable, Schedule, Window, load_nodes, select_node  # noqa: E402
from studio.nodes.bundle import sha256_file  # noqa: E402
from studio.nodes.client import NodeClient  # noqa: E402
from studio.nodes.remote import (  # noqa: E402
    REMOTE_STAGES,
    pull_job,
    split_stages,
    submit_project,
    wait_for_job,
)
from studio.worker.app import create_app  # noqa: E402
from studio.worker.service import WorkerService  # noqa: E402

from .conftest import make_project, needs_ffmpeg, three_scene_fixed  # noqa: E402

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _service(settings: Settings, tmp_path: Path, **kw) -> WorkerService:
    kw.setdefault("ignore_schedule", True)
    return WorkerService(settings, token=TOKEN, data_dir=tmp_path / "worker data", idle_probe=lambda: None,
                         gpu_probe=lambda: None, **kw)


@pytest.fixture
def worker(settings: Settings, tmp_path: Path):
    svc = _service(settings, tmp_path)
    with TestClient(create_app(svc)) as http:
        yield svc, http


def _client(http: TestClient, node_id: str = "home-gpu") -> NodeClient:
    return NodeClient(http, node_id, TOKEN)


# ------------------------------------------------------------------ schedule


def _utc(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def test_schedule_windows():
    s = Schedule.from_dict({"timezone": "Asia/Ho_Chi_Minh", "windows": ["mon-fri 08:30-17:30"]})
    # 2026-11-04 is a Wednesday; 03:00 UTC = 10:00 in Vietnam
    assert s.is_open(_utc(2026, 11, 4, 3, 0))
    assert not s.is_open(_utc(2026, 11, 4, 12, 0))          # 19:00 local
    assert not s.is_open(_utc(2026, 11, 7, 3, 0))           # Saturday
    nxt = s.next_open(_utc(2026, 11, 7, 3, 0))
    assert (nxt.weekday(), nxt.hour, nxt.minute) == (0, 8, 30)   # Monday 08:30 local
    night = Schedule.from_dict({"timezone": "UTC", "windows": ["sat,sun 22:00-06:00"]})
    assert night.is_open(_utc(2026, 11, 8, 2, 0))           # Sunday 02:00 belongs to Saturday's window
    assert night.is_open(_utc(2026, 11, 9, 5, 0))           # Monday 05:00 belongs to Sunday's window
    assert not night.is_open(_utc(2026, 11, 10, 2, 0))      # Tuesday 02:00
    assert Schedule.from_dict({}).is_open()                 # no windows = always
    assert Window.parse("daily 00:00-24:00").contains(datetime(2026, 1, 1, 23, 59))
    with pytest.raises(Exception, match="bad schedule"):
        Window.parse("weekdays 9-5")


# ------------------------------------------------------------------ worker API security


def test_requests_without_or_with_wrong_token_get_401(worker):
    _, http = worker
    assert http.get("/v1/health").status_code == 401
    assert http.get("/v1/health", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert http.get("/v1/jobs", headers={"Authorization": TOKEN}).status_code == 401
    assert http.post("/v1/jobs", json={}).status_code == 401
    r = http.get("/v1/health", headers=AUTH)
    assert r.status_code == 200 and r.json()["in_schedule"] is True


def _job(**over) -> dict:
    sha = "a" * 64
    return deep_merge({"type": "pipeline", "project_id": "p1", "stages": ["render"],
                       "files": [{"path": "project.json", "sha256": sha, "size": 1}]}, over)


@pytest.mark.parametrize("bad", [
    {"type": "shell"},
    {"type": "pipeline", "command": "calc.exe"},
    {"stages": ["exec"]},
    {"stages": []},
    {"files": [{"path": "../evil.txt", "sha256": "a" * 64, "size": 1}]},
    {"files": [{"path": "C:/Windows/evil.txt", "sha256": "a" * 64, "size": 1}]},
    {"files": [{"path": "clips\\a.mp4", "sha256": "a" * 64, "size": 1}]},
    {"files": [{"path": "a.mp4", "sha256": "not-a-sha", "size": 1}]},
    {"options": {"shell": True}},
])
def test_undefined_job_types_and_unsafe_requests_are_rejected(worker, bad):
    svc, http = worker
    r = http.post("/v1/jobs", json=_job(**bad), headers=AUTH)
    assert r.status_code == 422, r.text
    assert svc.queue.counts()["queued"] == 0


def test_blob_upload_is_verified(worker):
    _, http = worker
    data = b"hello worker"
    good = hashlib.sha256(data).hexdigest()
    assert http.put(f"/v1/blobs/{'0' * 64}", content=data, headers=AUTH).status_code == 400
    assert http.put("/v1/blobs/..%2Fx", content=data, headers=AUTH).status_code in (400, 404)
    assert http.put(f"/v1/blobs/{good}", content=data, headers=AUTH).json()["stored"] is True
    assert http.get(f"/v1/blobs/{good}", headers=AUTH).content == data
    assert http.post("/v1/blobs/missing", json={"sha256": [good, "b" * 64]}, headers=AUTH).json() == {
        "missing": ["b" * 64]}
    # a job whose blobs were never uploaded is refused
    assert http.post("/v1/jobs", json=_job(), headers=AUTH).status_code == 409


def test_cancel_queued_job(worker):
    svc, http = worker
    data = b"{}"
    sha = hashlib.sha256(data).hexdigest()
    http.put(f"/v1/blobs/{sha}", content=data, headers=AUTH)
    job_id = http.post("/v1/jobs", json=_job(files=[{"path": "project.json", "sha256": sha, "size": 2}]),
                       headers=AUTH).json()["id"]
    assert _client(http).cancel(job_id)["status"] == "cancelled"
    assert svc.process_one() is False
    assert _client(http).job(job_id)["status"] == "cancelled"


# ------------------------------------------------------------------ node selection


def _settings_with_node(settings: Settings, **node) -> Settings:
    data = deep_merge(settings.data, {"nodes": [{"id": "home-gpu", **node}]})
    return Settings(root=settings.root, data=data, formats=settings.formats)


def test_select_node_skips_disabled_tokenless_and_offline(settings, worker, monkeypatch):
    _, http = worker
    monkeypatch.delenv("STUDIO_NODE_HOME_GPU_TOKEN", raising=False)
    healthy = lambda node: _client(http)  # noqa: E731

    s = _settings_with_node(settings, enabled=False)
    assert select_node(s, "auto", client_factory=healthy) is None
    with pytest.raises(NodeUnavailable, match="disabled"):
        select_node(s, "home-gpu", client_factory=healthy)

    s = _settings_with_node(settings, enabled=True)
    with pytest.raises(NodeUnavailable, match="STUDIO_NODE_HOME_GPU_TOKEN"):
        select_node(s, "home-gpu", client_factory=healthy)

    monkeypatch.setenv("STUDIO_NODE_HOME_GPU_TOKEN", TOKEN)

    def offline(node):
        def boom(request):
            raise httpx.ConnectError("no route to host", request=request)
        return NodeClient(httpx.Client(base_url="http://home-gpu:8765", transport=httpx.MockTransport(boom)),
                          node.id, TOKEN)

    assert select_node(s, "auto", client_factory=offline) is None
    with pytest.raises(NodeUnavailable, match="unreachable"):
        select_node(s, "home-gpu", client_factory=offline)

    assert select_node(s, "auto", client_factory=healthy).id == "home-gpu"
    assert load_nodes(s)["home-gpu"].token == TOKEN


def _closed_schedule() -> Schedule:
    tomorrow = DAYS[(datetime.now(UTC).weekday() + 2) % 7]
    return Schedule.from_dict({"timezone": "UTC", "windows": [f"{tomorrow} 10:00-11:00"]})


def test_outside_schedule_auto_skips_node_and_job_waits(settings, tmp_path, monkeypatch):
    svc = _service(settings, tmp_path, ignore_schedule=False)
    svc.schedule = _closed_schedule()
    assert svc.paused_reason().startswith("outside schedule")
    monkeypatch.setenv("STUDIO_NODE_HOME_GPU_TOKEN", TOKEN)
    s = _settings_with_node(settings, enabled=True)
    with TestClient(create_app(svc)) as http:
        assert select_node(s, "auto", client_factory=lambda n: _client(http)) is None   # -> run locally
        assert select_node(s, "home-gpu", client_factory=lambda n: _client(http)).id == "home-gpu"
        data = b"{}"
        sha = hashlib.sha256(data).hexdigest()
        http.put(f"/v1/blobs/{sha}", content=data, headers=AUTH)
        r = http.post("/v1/jobs", json=_job(files=[{"path": "project.json", "sha256": sha, "size": 2}]),
                      headers=AUTH).json()
        assert r["paused_reason"].startswith("outside schedule")
        with pytest.raises(WaitingForNode) as ei:
            wait_for_job(_client(http), r["id"], poll_sec=0, timeout_sec=60, sleep=lambda s: None)
        assert ei.value.exit_code == EXIT_WAITING_NODE


def test_user_activity_and_busy_gpu_pause_the_worker(settings, tmp_path):
    svc = _service(settings, tmp_path, ignore_schedule=False)
    svc.schedule = Schedule()
    svc.policy = {"yield_if_user_active": True}
    svc._idle_probe = lambda: 30.0
    assert "user active" in svc.paused_reason()
    svc._idle_probe = lambda: 3600.0
    svc._gpu_probe = lambda: {"name": "RTX", "util_pct": 95, "mem_used_mb": 9000, "mem_total_mb": 10240}
    svc._gpu_cache = (0.0, None)
    assert "GPU busy" in svc.paused_reason()
    svc._gpu_probe = lambda: {"name": "RTX", "util_pct": 3, "mem_used_mb": 500, "mem_total_mb": 10240}
    svc._gpu_cache = (0.0, None)
    assert svc.paused_reason() is None


def test_worker_refuses_short_token(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_WORKER_TOKEN", "short")
    with pytest.raises(Exception, match="token"):
        WorkerService(settings, data_dir=tmp_path / "w")


# ------------------------------------------------------------------ voice location


def test_node_only_voice_is_refused_elsewhere(settings, tmp_path):
    from studio.pipeline.voice import _synthesize_all
    from studio.voices import VoiceProfile, load_registry

    ctx = make_project(tmp_path / "p", settings)
    prof = VoiceProfile(id="f5-vi", lang="vi", tier="local", provider="mock", location="node:home-gpu")
    with pytest.raises(ProviderUnavailable) as ei:
        _synthesize_all(ctx, load_registry(settings), prof, None, False)
    assert ei.value.code == "tts_wrong_node"


# ------------------------------------------------------------------ round trip


def test_split_stages():
    assert split_stages(["source", "script", "scenes", "validate", "voice", "render"]) == (
        ["source", "script", "scenes"], ["validate", "voice", "render"])
    assert split_stages(["storyboard", "media"]) == (["storyboard", "media"], [])


@needs_ffmpeg
def test_submit_run_pull_round_trip(settings, worker, tmp_path, monkeypatch):
    svc, http = worker
    client = _client(http)
    ctx = three_scene_fixed(tmp_path / "dự án thử nghiệm", settings)
    clips_before = {p.name: sha256_file(p) for p in (ctx.dir / "clips").iterdir()}

    job_id = submit_project(ctx, client, list(REMOTE_STAGES), {"strict": True})
    assert ctx.stage_status("render") == "remote"
    assert (ctx.dir / "work" / "remote_job.json").is_file()
    with pytest.raises(WaitingForNode):
        pull_job(ctx, client, job_id)                       # not run yet

    assert svc.process_one() is True
    job = client.job(job_id)
    assert job["status"] == "done", job["error"]
    assert pull_job(ctx, client, job_id) == 0

    final = ctx.dir / "output" / "final.mp4"
    assert final.is_file() and final.stat().st_size > 10_000
    qc = json.loads((ctx.dir / "output" / "qc_report.json").read_text(encoding="utf-8"))
    assert qc["status"] == "PASS"
    assert ctx.stage_status("package") == "done"
    assert "[home-gpu]" in ctx.state()["stages"]["render"]["message"]
    assert any("worker_" in p.name for p in (ctx.dir / "logs").iterdir())
    assert {p.name: sha256_file(p) for p in (ctx.dir / "clips").iterdir()} == clips_before
    assert not list((svc.data_dir / "jobs").glob("*"))      # workspace cleaned

    # re-submitting the unchanged project uploads nothing
    uploads = []
    monkeypatch.setattr(client, "upload", lambda sha, path: uploads.append(path))
    job2 = submit_project(ctx, client, ["qc", "package"], {})
    assert uploads == []
    assert svc.process_one() is True
    assert pull_job(ctx, client, job2) == 0


@needs_ffmpeg
def test_pull_keeps_local_edits_as_remote_copy(settings, worker, tmp_path):
    svc, http = worker
    client = _client(http)
    ctx = three_scene_fixed(tmp_path / "p2", settings)
    job_id = submit_project(ctx, client, ["validate", "voice"], {})   # voice rewrites project.json on the worker
    proj = ctx.dir / "project.json"
    edited = proj.read_text(encoding="utf-8").replace('"title": ""', '"title": "edited meanwhile"')
    proj.write_text(edited, encoding="utf-8")
    assert svc.process_one() is True
    assert pull_job(ctx, client, job_id) == 0
    assert proj.read_text(encoding="utf-8") == edited
    assert (ctx.dir / "project.remote.json").is_file()
    assert (ctx.dir / "work" / "timeline.json").is_file()


@needs_ffmpeg
def test_failed_remote_job_reports_exit_code(settings, worker, tmp_path):
    svc, http = worker
    client = _client(http)
    ctx = three_scene_fixed(tmp_path / "p3", settings)
    (ctx.dir / "clips" / "scene_02.mp4").write_bytes(b"not a video")
    job_id = submit_project(ctx, client, ["validate", "voice", "render"], {})
    svc.process_one()
    with pytest.raises(Exception) as ei:
        pull_job(ctx, client, job_id)
    assert ei.value.exit_code == 2                          # validation failed on the worker
    assert ctx.stage_status("validate") == "failed"
    assert any("worker_" in p.name for p in (ctx.dir / "logs").iterdir())


@needs_ffmpeg
def test_assets_travel_with_the_job(settings, tmp_path):
    """The controller's asset library is not on the worker: `asset:` refs are uploaded into a job overlay."""
    from studio.core.ffmpeg import run_ffmpeg

    ctrl_assets, worker_assets = tmp_path / "ctrl assets", tmp_path / "worker assets"
    worker_assets.mkdir()
    music = ctrl_assets / "shared" / "music" / "nhạc nền.wav"
    music.parent.mkdir(parents=True)
    run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:duration=30", str(music)], stage="fixture")
    shutil.copytree(settings.path("assets") / "shared" / "caption_styles", ctrl_assets / "shared" / "caption_styles")

    def with_assets(path: Path) -> Settings:
        return Settings(root=settings.root, formats=settings.formats,
                        data=deep_merge(settings.data, {"paths": {"assets": str(path)}}))

    svc = _service(with_assets(worker_assets), tmp_path)
    ctx = three_scene_fixed(tmp_path / "p4", with_assets(ctrl_assets))
    ctx.project.audio.background_music = "asset:shared/music/nhạc nền.wav"
    ctx.save()
    with TestClient(create_app(svc)) as http:
        client = _client(http)
        job_id = submit_project(ctx, client, list(REMOTE_STAGES), {})
        assert "shared/music/nhạc nền.wav" in [a["path"] for a in client.job(job_id)["request"]["assets"]]
        assert svc.process_one() is True
        assert client.job(job_id)["status"] == "done", client.job(job_id)["error"]
        assert pull_job(ctx, client, job_id) == 0
    assert (ctx.dir / "output" / "final.mp4").is_file()
    assert not any(worker_assets.iterdir())          # the worker's own library is untouched
