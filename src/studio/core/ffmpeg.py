"""Locate and run ffmpeg/ffprobe. Always argument lists, never shell=True."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path

from .errors import FFmpegError, ToolMissingError
from .logging_utils import get_logger

log = get_logger()


def _candidates(name: str) -> list[str]:
    exe = f"{name}.exe" if os.name == "nt" else name
    out: list[str] = [str(Path(__file__).resolve().parents[3] / 'tools' / 'ffmpeg' / 'bin' / exe)]
    env_dir = os.environ.get("STUDIO_FFMPEG_DIR")
    if env_dir:
        out.append(str(Path(env_dir) / exe))
    found = shutil.which(name)
    if found:
        out.append(found)
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        # winget (Gyan.FFmpeg / BtbN) installs here; PATH needs a new shell after install
        out.extend(sorted(glob.glob(rf"{local}\Microsoft\WinGet\Packages\*FFmpeg*\*\bin\{exe}"), reverse=True))
        out.append(rf"{local}\Microsoft\WinGet\Links\{exe}")
        out.extend([rf"C:\ffmpeg\bin\{exe}", rf"C:\ProgramData\chocolatey\bin\{exe}"])
    return out


@lru_cache(maxsize=4)
def find_tool(name: str) -> str:
    for c in _candidates(name):
        if c and Path(c).is_file():
            return c
    raise ToolMissingError(
        f"{name} not found. Install FFmpeg (winget install Gyan.FFmpeg) or set STUDIO_FFMPEG_DIR",
        code="ffmpeg_missing",
    )


def ffmpeg_bin() -> str:
    return find_tool("ffmpeg")


def ffprobe_bin() -> str:
    return find_tool("ffprobe")


def _fmt_cmd(args: list[str]) -> str:
    return " ".join(f'"{a}"' if (" " in a or not a) else a for a in args)


def run_ffmpeg(
    args: list[str],
    *,
    stage: str,
    scene_id: str | None = None,
    cwd: Path | None = None,
    timeout: float | None = None,
    loglevel: str = "error",
) -> str:
    """Run ffmpeg with `args` (without the binary); returns stderr. Raises FFmpegError with stderr tail on failure."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-loglevel", loglevel, *args]
    tag = f"[{stage}]" + (f"[{scene_id}]" if scene_id else "")
    log.debug("%s cmd: %s (cwd=%s)", tag, _fmt_cmd(cmd), cwd)
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    elapsed = time.monotonic() - t0
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-30:])
        log.error("%s ffmpeg exit %s after %.1fs\n%s", tag, proc.returncode, elapsed, tail)
        raise FFmpegError(f"ffmpeg failed at {stage}", returncode=proc.returncode, stderr_tail=tail, scene_id=scene_id)
    if proc.stderr.strip() and loglevel == "error":
        log.debug("%s ffmpeg stderr: %s", tag, proc.stderr.strip()[-2000:])
    log.debug("%s done in %.1fs", tag, elapsed)
    return proc.stderr or ""


def has_filter(name: str) -> bool:
    try:
        out = subprocess.run(
            [ffmpeg_bin(), "-hide_banner", "-filters"], capture_output=True, text=True, errors="replace", timeout=30
        ).stdout
    except (ToolMissingError, OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if len(line.split()) > 1)


def has_encoder(name: str) -> bool:
    try:
        out = subprocess.run(
            [ffmpeg_bin(), "-hide_banner", "-encoders"], capture_output=True, text=True, errors="replace", timeout=30
        ).stdout
    except (ToolMissingError, OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if len(line.split()) > 1)


def escape_filter_path(path: Path | str) -> str:
    """Escape a path for use as a filter option value (subtitles/ass/movie)."""
    s = str(path).replace("\\", "/")
    s = s.replace(":", r"\:").replace("'", r"\'")
    return f"'{s}'"
