"""Regression tests for mandatory review, safe publication and migrated entry points."""
import json
from pathlib import Path
import pytest

from studio.social_video import quality

def test_review_is_bound_to_current_video(tmp_path,monkeypatch):
    monkeypatch.setattr("studio.core.user_review.require",lambda *a:None)
    video=tmp_path/'video.mp4'; video.write_bytes(b'first')
    monkeypatch.setattr("studio.core.user_review.payload",lambda *a:{'videos':[{'path':str(video)}]})
    report={'automatic':'PASS','sha256':quality.sha256(video),'errors':[]}
    video.with_suffix('.qc.json').write_text(json.dumps(report))
    assert quality.approve(video,'Viewed all scenes and listened to narration','user',project=tmp_path)['status']=='PASS'
    video.write_bytes(b'edited')
    with pytest.raises(RuntimeError,match='stale'):
        quality.approve(video,'Same review','user',project=tmp_path)

def test_cannot_approve_failed_or_unchecked_video(tmp_path,monkeypatch):
    monkeypatch.setattr("studio.core.user_review.require",lambda *a:None)
    video=tmp_path/'video.mp4'; video.write_bytes(b'first')
    monkeypatch.setattr("studio.core.user_review.payload",lambda *a:{'videos':[{'path':str(video)}]})
    with pytest.raises(RuntimeError): quality.approve(video,'checked','user',project=tmp_path)
    with pytest.raises(ValueError): quality.approve(video,'','user')

def test_failed_candidate_never_replaces_previous_good_video(tmp_path,monkeypatch):
    draft=tmp_path/'draft.mp4';draft.write_bytes(b'draft')
    final=tmp_path/'final.mp4';final.write_bytes(b'good')
    monkeypatch.setattr(quality,'media_duration',lambda p:5.)
    monkeypatch.setattr(quality,'master',lambda src,out,*a:out.write_bytes(b'bad'))
    monkeypatch.setattr(quality,'inspect',lambda *a:{'errors':['audio clipped']})
    with pytest.raises(RuntimeError,match='QC failed'):
        quality.publish(draft,final,{})
    assert final.read_bytes()==b'good'

def test_native_cli_exposes_merged_not_legacy_interface():
    from studio.cli import app
    from typer.testing import CliRunner
    result=CliRunner().invoke(app,['--help'])
    assert result.exit_code==0
    assert 'threads-post' in result.stdout
    assert 'reddit-story' in result.stdout
    assert 'social-review' in result.stdout

def test_social_home_is_not_old_download_folder():
    from studio.social_video.util import ROOT,STUDIO_ROOT
    assert ROOT == STUDIO_ROOT/'projects/social_video'
    assert 'Downloads' not in str(ROOT)

def test_reddit_action_is_a_positional_argument(monkeypatch):
    from studio.cli import app
    from studio.social_video import reddit
    from typer.testing import CliRunner
    monkeypatch.setattr(reddit,'list_json',lambda cfg:'[]')
    result=CliRunner().invoke(app,['reddit-story','list'])
    assert result.exit_code==0, result.output
    assert '[]' in result.stdout

def test_documented_review_options_parse(monkeypatch,tmp_path):
    from studio.cli import app
    from typer.testing import CliRunner
    monkeypatch.setattr(quality,'approve',lambda *args,**kwargs:{'status':'PASS'})
    result=CliRunner().invoke(app,['social-review',str(tmp_path/'x.mp4'),
        '--reviewer','Codex','--note','Actual review'])
    assert result.exit_code==0,result.output

def test_missing_legacy_output_is_not_treated_as_produced(monkeypatch,tmp_path):
    from studio.social_video import reddit
    store=tmp_path/'stories'; (store/'s1').mkdir(parents=True)
    (store/'s1/source.json').write_text(json.dumps({'id':'s1','words':200,'title':'A complete story'}))
    done=tmp_path/'done.json'; done.write_text(json.dumps({'s1':{'files':['missing.mp4']}}))
    monkeypatch.setattr(reddit,'STORE',store)
    monkeypatch.setattr(reddit,'DONE',done)
    monkeypatch.setattr(reddit,'OUTPUT',tmp_path)
    assert reddit.candidates({'reddit':{'max_words':2500}})[0]['id']=='s1'
