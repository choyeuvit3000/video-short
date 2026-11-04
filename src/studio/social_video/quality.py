"""Mandatory Studio QC and hash-bound editorial review for social videos."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from studio.core.qc import check_media
from studio.core.qc_analysis import analyze_av
from .studio_bridge import master
from .util import ffmpeg, media_duration, read_json, run, write_json

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def inspect(path: Path, expected: float | None = None) -> dict:
    media, errors, warnings = check_media(path, width=1080, height=1920, fps=30,
        expected_sec=expected, tolerance_sec=.5)
    duration = media.get('duration_sec', 0)
    analysis = analyze_av(path, duration) if duration else {}
    loud = analysis.get('integrated_lufs')
    peak = analysis.get('true_peak_db')
    if loud is None or not -20 <= loud <= -9:
        errors.append(f'Unexpected loudness: {loud} LUFS')
    if peak is None or peak > -.5:
        errors.append(f'Audio true peak unsafe: {peak}')
    dark = sum(b-a for a,b in analysis.get('black', []))
    if duration and dark > duration * .5:
        errors.append('More than half the video is black')
    if analysis.get('freeze'):
        warnings.append('Static cards/borders may trigger freeze detection: inspect the sheet and moving clip')
    if analysis.get('silence'):
        warnings.append('Check pauses in context; no automatic deletion of source pauses')
    sheet = path.with_suffix('.sheet.jpg')
    interval = max(duration / 11, .5)
    run([ffmpeg(), '-y', '-v', 'error', '-i', str(path), '-an', '-vf',
         f'fps=1/{interval:.5f},scale=216:-1,tile=4x3', '-frames:v','1',str(sheet)])
    report = {'status': 'FAIL' if errors else 'REVIEW_REQUIRED', 'automatic': 'FAIL' if errors else 'PASS',
        'editorial': 'PENDING', 'sha256': sha256(path), 'media': media,
        'analysis': analysis, 'errors': errors, 'warnings': warnings,
        'sheet': sheet.name, 'review_requirements': [
            'Original content and source credit accurate; no invented narrative',
            'Text readable; no important text obscured by meme or platform UI',
            'Original media complete unless explicitly edited; no accidental freezes',
            'Check narration/source audio by listening or documented local ASR plus audio meters; do not claim listening if only ASR was used',
            'Meme/sound appropriate; no clipping or abrupt cuts']}
    write_json(path.with_suffix('.qc.json'), report)
    return report

def approve(path: Path, note: str, reviewer: str) -> dict:
    report = read_json(path.with_suffix('.qc.json'), {})
    if not note.strip() or not reviewer.strip():
        raise ValueError('Reviewer and concrete review note are required')
    if report.get('automatic') != 'PASS' or report.get('sha256') != sha256(path):
        raise RuntimeError('QC missing, failed, or stale; run social-qc again')
    report.update(status='PASS', editorial='APPROVED', reviewer=reviewer, review_note=note)
    write_json(path.with_suffix('.qc.json'), report)
    return report

def publish(draft: Path, out: Path, cfg: dict, credit: Path | None = None) -> Path:
    """Keep previous good output on failure; never mark an unreviewed video approved."""
    from studio.core.paths import find_repo_root
    candidate = out.with_name(out.stem + '.candidate.mp4')
    expected = media_duration(draft)
    master(draft, candidate, find_repo_root(), credit)
    report = inspect(candidate, expected)
    if report['errors']:
        raise RuntimeError(f"QC failed; candidate retained: {report['errors']}")
    if out.exists():
        from studio.core.outputs import archive_previous
        # Use a per-video history folder, not Studio's project-wide final.mp4 convention.
        history = out.parent / '_history' / out.stem
        history.mkdir(parents=True, exist_ok=True)
        old = history / (sha256(out)[:12] + '.mp4')
        if not old.exists():
            import shutil
            shutil.copy2(out, old)
    candidate.replace(out)
    candidate.with_suffix('.sheet.jpg').replace(out.with_suffix('.sheet.jpg'))
    report['sheet'] = out.with_suffix('.sheet.jpg').name
    write_json(out.with_suffix('.qc.json'), report)
    candidate.with_suffix('.qc.json').unlink(missing_ok=True)
    return out
