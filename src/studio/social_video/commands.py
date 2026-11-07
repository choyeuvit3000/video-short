"""Merged-result Threads posts and migrated Reddit stories, inside Studio."""
from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Annotated

import typer
from PIL import Image, ImageDraw, ImageFont
from .util import ROOT, OUTPUT, FINAL_OUTPUT, load_config, media_duration, read_json, write_json

def threads_post(source: str, narration_file: Path | None = None, plan_file: Path | None = None) -> Path:
    from . import memes
    from .post_renderer import StoryRenderer
    from .render import _concat_raw
    from .quality import publish
    cfg = load_config()
    cfg['bgm']['enabled'] = False
    cfg['story']['background'] = 'blur'
    cfg['story']['video_clip_sec'] = 600
    cfg['video']['max_segment_sec'] = 600
    if source.startswith('https://'):
        url = source.split('?')[0].rstrip('/')
        from .capture import POST_RE, capture_posts
        if not POST_RE.fullmatch(url):
            raise ValueError('Expected a public Threads post URL')
        from playwright.sync_api import sync_playwright
        wd = ROOT/'work/threads'/url.rsplit('/',1)[-1]
        wd.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge',headless=True)
            try:
                posts = capture_posts(browser,[url],wd,cfg)
            finally:
                browser.close()
        if not posts:
            raise RuntimeError('No accessible source post; do not invent content')
        write_json(wd/'posts.json',posts)
    else:
        wd = Path(source).resolve()
        posts = read_json(wd/'posts.json',[])
    if len(posts) != 1:
        raise ValueError('threads-post expects exactly one captured post')
    post = posts[0]
    texts = post.get('part_texts') or []
    # Editorial spelling/number normalization may be supplied, without rewriting facts.
    narrations = read_json(narration_file) if narration_file else texts
    if len(narrations) != len(post['parts']):
        raise ValueError('Narration list must match post parts')
    beats=[]
    def add(kind,ref,text=''):
        beats.append(dict(kind=kind,ref=ref,narration=text,image_id='',sound_id='',
                          caption_top='',caption_bottom=''))
    add('post',0,narrations[0])
    for k, media in enumerate(post.get('media',[])):
        add('media',k)
    for k in range(1,len(post['parts'])):
        add('post',k,narrations[k])
    if plan_file:
        editorial = read_json(plan_file)
        if editorial.get('source') != post['url']:
            raise ValueError('Editorial plan must identify the exact captured source URL')
        beats = editorial['beats']
        library = {i['id']:i for i in memes.load()['items']}
        for beat in beats:
            kind = beat['kind']
            if kind not in ('post','media','comment','reaction'):
                raise ValueError('Unknown beat kind')
            collection = {'post':post['parts'],'media':post.get('media',[]),
                          'comment':post.get('comments',[])}.get(kind)
            if collection is not None and not 0 <= beat['ref'] < len(collection):
                raise ValueError('Beat reference out of range')
            for key in ('image_id','sound_id'):
                if beat.get(key) and beat[key] not in library:
                    raise ValueError(f'Unknown asset: {beat[key]}')
    write_json(wd/'merged_plan.json',{'style':'approved-merged-v1','source':post['url'],'beats':beats})
    from ..core.creative_brief import begin_social,complete_social
    key,cached=begin_social(wd,cfg)
    if cached:
        print(f'UP_TO_DATE: {cached[0]}',flush=True)
        return cached[0]
    try:
        r = StoryRenderer(cfg,wd,memes.load(),post,'merged')
        hook = texts[0] if texts and len(texts[0].split()) <= 8 else ''
        clips=[r.render_beat(k,b,hook if k==0 else '') for k,b in enumerate(beats)]
        draft = wd/'merged_draft.mp4'
        _concat_raw(clips,wd,draft,cfg,name='merged_joined')
        credit=Image.new('RGBA',(1080,1920),(0,0,0,0))
        draw=ImageDraw.Draw(credit)
        draw.rounded_rectangle((60,220,940,315),radius=20,fill=(16,16,16,235))
        draw.text((85,240),'Threads · @'+post['author'],fill='white',
                  font=ImageFont.truetype(cfg['fonts']['body'],40))
        credit.save(wd/'credit.png')
        tag=post['url'].rstrip('/').rsplit('/',1)[-1]
        from studio.core.outputs import organized_output
        folder = organized_output(FINAL_OUTPUT, 'threads', wd/'output_location.json')
        out=folder/f'threads__{tag}.mp4'
        out.parent.mkdir(parents=True,exist_ok=True)
        publish(draft,out,cfg,wd/'credit.png')
        write_json(out.with_suffix('.source.json'),{'url':post['url'],'author':post['author'],
            'style':'approved-merged-v1','voice_engine':cfg['tts']['engines'][0],
            'voice':cfg['tts'].get(cfg['tts']['engines'][0],{}).get('profile') or cfg['tts'].get('vieneu',{}).get('voice'),
            'source_media_sec':[media_duration(wd/m['file']) for m in post.get('media',[]) if m['kind']=='video']})
    except Exception:
        from ..core.creative_brief import finish_render
        finish_render(wd,False)
        raise
    complete_social(wd,key,[out])
    print(f'REVIEW_REQUIRED: {out}',flush=True)
    return out

def register(app):
    @app.command('funny-threads')
    def funny_threads(project: Path, action: str = 'layouts'):
        """Prepare layouts, checked edits, voice audition, or a Funny Threads render."""
        from ..cli import _guard
        from ..core.outputs import organized_output
        from . import funny_threads as funny

        def body():
            folder = project.resolve()
            if action == 'layouts':
                result = funny.layouts(folder)
            elif action == 'voice':
                result = funny.prepare_voice(folder)
            elif action == 'reedit':
                result = funny.prepare_voice(folder, reuse_checked=True)
            elif action == 'check-speech':
                result = funny.check_speech(folder)
            elif action == 'render':
                output = organized_output(FINAL_OUTPUT, 'funny_threads', folder/'output_location.json')
                edit = funny.read(folder/'funny_edit.json')
                suffix = f"__v{int(edit['revision'])}" if edit else ''
                result = funny.render(folder, output/f'funny_threads__{folder.name}{suffix}.mp4')
            else:
                raise typer.BadParameter('Use --action layouts / voice / reedit / check-speech / render')
            print(result)
            return 0
        _guard(body)

    @app.command('story-draft-review')
    def story_draft_review(draft: Path, output: Annotated[Path | None, typer.Option('--output')] = None):
        """Rà độ dài/câu mở/giác quan/nhịp cao trào, không tạo giọng hoặc tự duyệt."""
        from .story_editorial import write_review
        path, report = write_review(draft, output)
        print(f"{report['status']}: {path.resolve()}")
        for item in report['episodes']:
            print(f"{item['episode']}: {item['space_separated_units']} units; {len(item['warnings'])} editorial warnings")

    @app.command('threads-post')
    def post(source: str, narration_file: Path | None = None, plan_file: Path | None = None):
        """Threads post using the approved merged layout; no story adaptation."""
        from ..cli import _guard
        _guard(lambda: (threads_post(source,narration_file,plan_file),0)[1])

    @app.command('reddit-story')
    def reddit_story(action: Annotated[str, typer.Argument()] = 'render', id: str | None = None, count: int = 1):
        """Migrated Reddit fetch/prep/render/auto; all outputs require QC and review."""
        from . import reddit
        cfg=load_config()
        if action=='fetch': reddit.fetch(cfg['reddit']['sub'],cfg['reddit']['period'])
        elif action=='list': print(reddit.list_json(cfg))
        elif action=='prep' and id: print(reddit.prep(id))
        elif action=='voice' and id:
            from .review_voice import prepare_voice
            from ..cli import _guard
            _guard(lambda:(print(prepare_voice(reddit.STORE/id)),0)[1])
        elif action=='render' and id:
            from ..cli import _guard
            _guard(lambda:(print(reddit.render(id,cfg)),0)[1])
        elif action=='auto':
            from ..cli import _guard
            _guard(lambda:(print(reddit.auto(cfg,count,cfg['reddit']['translator'])),0)[1])
        else: raise typer.BadParameter('Use fetch/list/prep --id ID/render --id ID/auto')

    @app.command('social-voice')
    def social_voice(project: Path):
        from .review_voice import prepare_voice
        from ..cli import _guard
        _guard(lambda:(print(prepare_voice(project)),0)[1])

    @app.command('social-qc')
    def qc(video: Path):
        from .quality import inspect
        result=inspect(video.resolve())
        print(result)
        if result['errors']: raise typer.Exit(5)

    @app.command('social-review')
    def review(video: Path, note: Annotated[str, typer.Option()], reviewer: Annotated[str, typer.Option()], project: Path | None = None):
        """Record actual editorial review, bound to the video's current SHA256."""
        from .quality import approve
        print(approve(video.resolve(),note,reviewer,project=project)['status'])

    @app.command('social-assets')
    def assets(action: Annotated[str, typer.Argument()] = 'scan', source: Path | None = None, seconds: float = 60):
        from . import memes
        if action=='scan': memes.scan()
        elif action=='refresh-funny':
            from .reaction_assets import refresh
            print(refresh())
        elif action=='fetch': memes.fetch(load_config())
        elif action=='import-background' and source:
            from .prepare_assets import import_background
            result = import_background(source, seconds)
            print({k:v for k,v in result.items() if k!='clips'})
        else:
            raise typer.BadParameter(
                'Use scan, fetch, refresh-funny, or import-background --source VIDEO [--seconds 60]')

    @app.command('reddit-publish-plan')
    def publish_plan():
        """Read the migrated publishing plan. Does not publish or change its schedule."""
        from .schedule import PLAN
        print(read_json(PLAN,[]))
