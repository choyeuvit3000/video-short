"""Build reusable Vietnamese reactions and silent portrait background segments.

Run with the existing Video-maker Python: prepare_vn_assets.py [--backgrounds].
Original footage and installed models are never modified.
"""
import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from .util import ASSETS, MEMES, ffmpeg, media_duration, read_json, run, write_json

REACTIONS = [
    ('ua-gi-vay', 'ỦA, GÌ VẬY?', 'huh-37baoro', 'bất ngờ, khó hiểu'),
    ('toi-cong-chuyen', 'TỚI CÔNG CHUYỆN!', 'goi-goi-toi-cong-chuyen', 'plot twist, rắc rối'),
    ('muoi-diem', 'MƯỜI ĐIỂM!', '10-diem', 'khen, thành công'),
    ('vi-tien', 'VÍ TÔI: CỨU!', 'applepay', 'mua sắm, trả phí'),
    ('dung-hinh', 'ĐỨNG HÌNH MẤT NĂM GIÂY', 'record-scratch-clean', 'ngỡ ngàng'),
    ('cuoi-ra-nuoc-mat', 'CƯỜI RA NƯỚC MẮT', 'spongebob-fail', 'thất bại nhẹ, tự trào'),
]

def reactions():
    meta = read_json(MEMES / 'meta.json', {})
    font = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 44)
    for slug, title, sound, context in REACTIONS:
        rel = f'images/vietnam/{slug}.png'
        path = MEMES / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new('RGB', (720, 720), '#ffdf57')
        d = ImageDraw.Draw(im)
        d.ellipse((190, 105, 530, 445), fill='#fff5cd', outline='#222222', width=10)
        d.ellipse((265, 210, 290, 250), fill='#222222')
        d.ellipse((430, 210, 455, 250), fill='#222222')
        if slug in ('muoi-diem', 'cuoi-ra-nuoc-mat'):
            d.arc((265, 255, 455, 390), 0, 180, fill='#222222', width=14)
            if slug == 'cuoi-ra-nuoc-mat':
                d.ellipse((240, 265, 265, 325), fill='#339dee')
                d.ellipse((455, 265, 480, 325), fill='#339dee')
        elif slug == 'vi-tien':
            d.arc((285, 335, 435, 415), 180, 360, fill='#222222', width=12)
        elif slug == 'dung-hinh':
            d.line((290, 340, 430, 340), fill='#222222', width=12)
        else:
            d.ellipse((325, 300, 395, 385), fill='#222222')
        words = title.split(); lines = []; line = ''
        for word in words:
            candidate = (line + ' ' + word).strip()
            if d.textlength(candidate, font=font) > 650:
                lines.append(line); line = word
            else:
                line = candidate
        lines.append(line)
        for n, line in enumerate(lines):
            d.text((360, 495+n*58), line, font=font, fill='#222222', anchor='mt')
        im.save(path)
        meta[rel] = {'name': f'{title} — {context}', 'source': 'threadreel-original',
                     'panels': 1, 'tag': 'vn-curated'}
        audio = MEMES / 'sounds' / 'myinstants' / (sound + '.mp3')
        video = MEMES / 'videos' / 'vietnam' / (slug + '.mp4')
        video.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg(), '-y', '-v', 'error', '-loop', '1', '-i', str(path)]
        if audio.exists():
            cmd += ['-i', str(audio)]
        cmd += ['-t', '2.4', '-vf', "scale=760:760,crop=720:720:x='20+8*sin(t*18)':y=20,fade=t=in:d=0.12",
                '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p']
        if audio.exists():
            cmd += ['-af', 'apad,alimiter=limit=0.85', '-c:a', 'aac']
        run(cmd + [str(video)])
        meta[video.relative_to(MEMES).as_posix()] = {
            'name': f'{title} — {context}', 'source': 'threadreel-original', 'tag': 'vn-curated'}
    for audio in (ASSETS / 'sfx').rglob('*'):
        if audio.suffix.lower() not in {'.mp3', '.wav', '.ogg'}:
            continue
        dest = MEMES / 'sounds' / 'effects_vn' / audio.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio, dest)
        meta[dest.relative_to(MEMES).as_posix()] = {
            'name': audio.stem.replace('-', ' '), 'source': 'local-sfx', 'tag': 'vn-curated'}
    write_json(MEMES / 'meta.json', meta)

def backgrounds(seconds=60):
    folder = ASSETS / 'bgclips' / 'prepared'
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for source in sorted((ASSETS / 'backgrounds').glob('*')):
        if source.suffix.lower() not in {'.mp4', '.webm', '.mov', '.mkv'}:
            continue
        total = media_duration(source)
        end = total - 3
        start = 3.0
        index = 0
        identity = hashlib.sha256(f'{source.name}|{source.stat().st_size}|{source.stat().st_mtime_ns}|{seconds}'.encode()).hexdigest()[:12]
        while start < end - 8:
            duration = min(seconds, end-start)
            dest = folder / f'{identity}_{index:03d}.mp4'
            if not dest.exists():
                partial = dest.with_suffix('.partial.mp4')
                run([ffmpeg(), '-y', '-v', 'error', '-ss', str(start), '-i', str(source),
                    '-t', str(duration), '-map', '0:v:0', '-an', '-c:v', 'copy',
                    '-avoid_negative_ts', 'make_zero', '-movflags', '+faststart', str(partial)])
                partial.replace(dest)
            entries.append({'file': dest.relative_to(ASSETS).as_posix(),
                            'source': source.name, 'start': start,
                            'requested_duration': duration, 'duration': media_duration(dest)})
            print(f'Background: {source.name[:32]} @ {start:.0f}s', flush=True)
            start += seconds; index += 1
    write_json(folder / 'manifest.json', {'clips': entries})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backgrounds', action='store_true')
    parser.add_argument('--seconds', type=float, default=60)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds < 10:
        parser.error('--seconds must be at least ten seconds')
    reactions()
    if args.backgrounds:
        backgrounds(args.seconds)
