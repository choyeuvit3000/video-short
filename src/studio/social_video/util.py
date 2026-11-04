"""Shared helpers: paths, config, external binaries, logging."""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parents[3]
ROOT = Path(os.environ.get('STUDIO_SOCIAL_HOME', str(STUDIO_ROOT / 'projects' / 'social_video'))).resolve()
WORK = ROOT / "work"
OUTPUT = ROOT / "output"  # legacy publishing state only
FINAL_OUTPUT = STUDIO_ROOT / "output"
MEMES = ROOT / "memes"
ASSETS = ROOT / "assets"
INPUTS = ROOT / "inputs"

DEFAULT_CONFIG = {
    "accounts": [],
    "lookback_hours": 24,
    "max_posts": 8,
    "thread_max_parts": 5,
    "include_comments": 2,
    "narration_mode": "summary",
    "subtitles": True,
    "video": {"width": 1080, "height": 1920, "fps": 30, "min_segment_sec": 5, "max_segment_sec": 45},
    "tts": {
        "enabled": True,
        "engines": ["vieneu"],
        "strict": True,
        "vieneu": {
            "python": os.environ.get("STUDIO_VIENEU_PYTHON", "D:/studio-node/tts/vieneu/.venv/Scripts/python.exe"),
            "runner": str(STUDIO_ROOT / "src/studio/providers/tts/vieneu_runner.py"),
            "hf_home": os.environ.get("HF_HOME", "D:/studio-node/hf"),
            "voice": "Mai Anh", "temperature": 0.7, "speed": 1.08,
        },
        "voice": "vi-VN-HoaiMyNeural",
        "rate": "+60%",
        # "Truyện Audio (tiết kiệm)": Vivibe economy voice, 1 credit = 3 characters
        "vivibe": {"api_key": "", "voice_id": "mhsL3CPLxmLYdSTKp3GANz", "speed": 1.35},
        # revidapi.com, 15 credits / 1000 characters; 9004 = "Truyện Audio" (9054 = "Minh Đàm")
        "revid": {"api_key": "", "voice_id": 9004, "speed": 1.35},
        # Voices per role in multi-voice stories (reddit mode). edge = [voice, pitch, rate]:
        # the two free Vietnamese neural voices, re-pitched into different characters.
        "cast": {
            "narrator_female": {"vivibe": "mhsL3CPLxmLYdSTKp3GANz", "revid": 9004,
                                "edge": ["vi-VN-HoaiMyNeural", "+0Hz"]},
            "narrator_male": {"vivibe": "mhsL3CPLxmLYdSTKp3GANj", "revid": 9054,
                              "edge": ["vi-VN-NamMinhNeural", "+0Hz"]},
            "male": {"revid": 9057, "edge": ["vi-VN-NamMinhNeural", "-9Hz"]},
            "male2": {"revid": 9018, "edge": ["vi-VN-NamMinhNeural", "+8Hz"]},
            "female": {"revid": 9023, "edge": ["vi-VN-HoaiMyNeural", "+12Hz"]},
            "female2": {"revid": 9049, "edge": ["vi-VN-HoaiMyNeural", "-10Hz"]},
            "child": {"revid": 9085, "edge": ["vi-VN-HoaiMyNeural", "+35Hz", "+70%"]},
            "old_male": {"revid": 9001, "edge": ["vi-VN-NamMinhNeural", "-20Hz", "+45%"]},
            "old_female": {"revid": 9050, "edge": ["vi-VN-HoaiMyNeural", "-18Hz", "+45%"]},
            "creepy": {"revid": 9054, "edge": ["vi-VN-NamMinhNeural", "-32Hz", "+35%"]},
        },
    },
    "ai": {"planner": "auto", "api_model": "claude-opus-5-5", "effort": "medium", "cli_model": ""},
    "memes": {
        "per_segment_max": 2,
        "imgflip_top": 60,
        "myinstants_vn_pages": 2,
        "sound_queries": [],
    },
    "bgm": {"enabled": True, "volume": 0.15},
    "mode": "digest",
    "reddit": {
        "sub": "nosleep",
        "period": "month",
        "max_words": 2500,
        "part_max_sec": 176,
        "translator": "auto",
        "watermark": "",
        "ambience_volume": 0.18,
        "music_volume": 0.4,   # horror score under the voice (ducked while someone speaks)
        "wait_for_vivibe": True,
    },
    "story": {
        "comments": 4,
        "max_media": 4,
        "max_sec": 75,
        "video_clip_sec": 15,
        "background": "auto",
        "series": "Threads",
        "watermark": "",
        "subtitles": False,
    },
    "fonts": {
        "title": "C:/Windows/Fonts/seguibl.ttf",
        "body": "C:/Windows/Fonts/arialbd.ttf",
        "subtitle_name": "Arial",
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    path = ROOT / "config.json"
    user = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    cfg = _merge(DEFAULT_CONFIG, user)
    cfg['tts']['engines'] = ['vieneu']
    cfg['tts']['strict'] = True
    return cfg


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_bin(name: str) -> str | None:
    """Locate an executable, including winget installs not yet on PATH."""
    local = STUDIO_ROOT / 'tools' / 'ffmpeg' / 'bin' / f'{name}.exe'
    if local.is_file():
        return str(local)
    found = shutil.which(name)
    if found:
        return found
    pattern = os.path.expandvars(
        rf"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\*\bin\{name}.exe"
    )
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None


def ffmpeg() -> str:
    exe = find_bin("ffmpeg")
    if not exe:
        raise SystemExit("Không tìm thấy ffmpeg. Cài bằng: winget install Gyan.FFmpeg")
    return exe


def ffprobe() -> str:
    exe = find_bin("ffprobe")
    if not exe:
        raise SystemExit("Không tìm thấy ffprobe (đi kèm ffmpeg).")
    return exe


def run(cmd: list[str], cwd: Path | None = None, input_text: str | None = None,
        timeout: int | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd, cwd=cwd, input=input_text, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-25:])
        raise RuntimeError(f"Lệnh lỗi ({proc.returncode}): {Path(cmd[0]).name}\n{tail}")
    return proc


def media_duration(path: Path) -> float:
    out = run([ffprobe(), "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)]).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def has_audio(path: Path) -> bool:
    out = run([ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries",
               "stream=index", "-of", "csv=p=0", str(path)]).stdout.strip()
    return bool(out)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
