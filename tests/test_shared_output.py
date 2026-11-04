from pathlib import Path
from studio.core.config import Settings, deep_merge
from studio.core.project import ProjectContext
from studio.core.outputs import archive_project
from studio.nodes.bundle import project_manifest, apply_results
from studio.core.cache import HashCache, file_sha256
from tests.conftest import make_project, color_clip

def central(settings, tmp_path):
    return Settings(settings.root, deep_merge(settings.data, {"paths":{"output":str(tmp_path/"shared")}}), settings.formats)

def test_modes_and_same_id_projects_do_not_collide(settings,tmp_path):
    s=central(settings,tmp_path)
    a=make_project(tmp_path/"a",s,project_id="same",workflow="story_reader")
    b=make_project(tmp_path/"b",s,project_id="same",workflow="story_reader")
    assert a.final_video.parent==b.final_video.parent==tmp_path/"shared"
    assert a.final_video!=b.final_video
    assert a.result_path("qc_report.json").name==a.result_stem+".qc.json"

def test_history_is_scoped_per_project(settings,tmp_path):
    s=central(settings,tmp_path)
    a=make_project(tmp_path/"a",s); b=make_project(tmp_path/"b",s)
    a.final_video.write_bytes(b"a");b.final_video.write_bytes(b"b")
    archived=archive_project(a)
    assert (archived/a.final_video.name).read_bytes()==b"a"
    assert b.final_video.read_bytes()==b"b"

def test_central_output_is_in_remote_manifest_and_pull(settings,tmp_path):
    ctx=make_project(tmp_path/"p",central(settings,tmp_path))
    ctx.final_video.write_bytes(b"original")
    hc=HashCache(tmp_path/"hashes.json")
    files=project_manifest(ctx,hc,include_output=True)
    assert any(f["path"]=="output/final.mp4" for f in files)
    payload=tmp_path/"payload";payload.write_bytes(b"remote")
    results=[{"path":"output/final.mp4","sha256":file_sha256(payload)}]
    import shutil
    apply_results(ctx,results,{},lambda sha,dest:shutil.copy2(payload,dest))
    assert ctx.final_video.read_bytes()==b"remote"
    assert not (ctx.dir/"output/final.mp4").exists()

def test_social_modes_use_same_root():
    from studio.social_video.util import FINAL_OUTPUT,STUDIO_ROOT
    assert FINAL_OUTPUT==STUDIO_ROOT/"output"


def test_shared_render_qc_package_and_cache(settings,tmp_path):
    from studio.core.schema import Scene, VisualSpec
    from studio.pipeline.runner import run_pipeline, RunOptions
    from studio.pipeline.fingerprint import outputs_for, output_shas
    ctx=make_project(tmp_path/"p",central(settings,tmp_path),
        scenes=[Scene(scene_id="s1",narration="Kiểm tra output chung.",
                      visual=VisualSpec(type="color",color="#345678"))])
    ro=RunOptions(only=["validate","voice","render","qc","package"])
    run_pipeline(ctx,ro)
    assert ctx.final_video.is_file()
    assert ctx.result_path("qc_report.json").is_file()
    assert ctx.result_path("metadata.md").is_file()
    assert not (ctx.output/"final.mp4").exists()
    assert output_shas(ctx,"render")["output/final.mp4"]
    original=ctx.final_video.stat().st_mtime_ns
    run_pipeline(ctx,RunOptions(only=["render","qc","package"]))
    assert ctx.final_video.stat().st_mtime_ns==original
