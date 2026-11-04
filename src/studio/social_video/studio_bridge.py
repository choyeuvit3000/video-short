"""Reuse the installed Studio renderer/QC without copying or changing its code."""
import os
import sys
import json
from pathlib import Path

from .util import ffmpeg, media_duration, run, write_json

def activate(studio_root: Path):
    src = str(studio_root / 'src')
    if src not in sys.path:
        sys.path.insert(0, src)
    os.environ['STUDIO_FFMPEG_DIR'] = str(Path(ffmpeg()).parent)

def master(source: Path, destination: Path, studio_root: Path, overlay: Path | None = None):
    """Studio-style loudness target + safe atomic publication, preserving source video."""
    activate(studio_root)
    from studio.core.qc import check_media
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix('.tmp.mp4')
    try:
        measurement = run([ffmpeg(), '-v', 'info', '-i', str(source), '-vn', '-af',
            'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-']).stderr
        measured = json.loads(measurement[measurement.rfind('{'):measurement.rfind('}')+1])
        norm = ('loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:'
                f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}")
        video = ['-map', '0:v:0', '-c:v', 'copy']
        inputs = ['-i', str(source)]
        if overlay:
            inputs += ['-loop', '1', '-framerate', '30', '-i', str(overlay)]
            video = ['-filter_complex', '[0:v][1:v]overlay=0:0:shortest=1[v]', '-map', '[v]',
                     '-r', '30', '-fps_mode', 'cfr', '-c:v', 'h264_nvenc', '-cq', '20', '-pix_fmt', 'yuv420p']
        run([ffmpeg(), '-y', '-v', 'error', *inputs, *video,
             '-map', '0:a:0', '-af', norm,
             '-ar', '48000', '-ac', '2', '-c:a', 'aac', '-b:a', '192k',
             '-t', str(media_duration(source)), '-movflags', '+faststart', str(tmp)])
        report, errors, warnings = check_media(tmp, width=1080, height=1920, fps=30,
            expected_sec=None, tolerance_sec=.5)
        write_json(destination.with_suffix('.qc.json'),
                   {'media': report, 'errors': errors, 'warnings': warnings})
        if errors:
            raise RuntimeError(f'Merged output failed QC: {errors}')
        tmp.replace(destination)
    finally:
        tmp.unlink(missing_ok=True)
    return destination
