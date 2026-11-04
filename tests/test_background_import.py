import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from studio.social_video import prepare_assets as assets

def test_targeted_split_preserves_old_manifest_and_reuses_segments(tmp_path,monkeypatch):
    monkeypatch.setattr(assets,"ASSETS",tmp_path)
    folder=tmp_path/"bgclips/prepared";folder.mkdir(parents=True)
    old={"file":"bgclips/prepared/old.mp4","source":"old.mp4","duration":60}
    (folder/"manifest.json").write_text(json.dumps({"clips":[old]}))
    source=tmp_path/"new.mp4";source.write_bytes(b"source")
    monkeypatch.setattr(assets,"media_duration",lambda p:26 if p==source else 10)
    monkeypatch.setattr(assets,"ffmpeg",lambda:"ffmpeg")
    calls=[]
    def run(cmd):
        calls.append(cmd);Path(cmd[-1]).write_bytes(b"clip")
    monkeypatch.setattr(assets,"run",run)
    clips=assets.backgrounds(10,[source])
    assert len(clips)==2
    assert old in json.loads((folder/"manifest.json").read_text())["clips"]
    assert all("-an" in c and c[c.index("-c:v")+1]=="copy" for c in calls)
    assert assets.backgrounds(10.0,[source])==clips
    assert len(calls)==2
    assert len(json.loads((folder/"manifest.json").read_text())["clips"])==3

@pytest.mark.parametrize("seconds",[0,-1,9,float("nan"),float("inf")])
def test_split_rejects_invalid_duration(seconds):
    with pytest.raises(ValueError):assets.backgrounds(seconds)

def test_generic_story_mode_can_select_shared_background(tmp_path):
    from studio.workflows.story_reader import _pick_background
    folder=tmp_path/"shared/backgrounds";folder.mkdir(parents=True)
    (folder/"minecraft.mp4").write_bytes(b"placeholder")
    ctx=SimpleNamespace(settings=SimpleNamespace(path=lambda key:tmp_path),
                        project=SimpleNamespace(project_id="demo"))
    assert _pick_background(ctx)=="asset:shared/backgrounds/minecraft.mp4"
