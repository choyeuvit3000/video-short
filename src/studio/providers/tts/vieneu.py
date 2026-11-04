"""VieNeu-TTS v3 Turbo (Apache-2.0, GPU) through a worker process in its own venv.

The model needs torch 2.8 + transformers pinned by VieNeu, so it lives in a separate venv
(scripts/install_vieneu.ps1, default D:\\studio-node\\tts\\vieneu). One `vieneu_runner.py` process is started on
first use and kept for the whole run (the model loads once, ~45 s); requests go over stdin/stdout as JSON lines.

config/local.yaml:
    tts:
      vieneu: {python: D:\\studio-node\\tts\\vieneu\\.venv\\Scripts\\python.exe, hf_home: D:\\studio-node\\hf}
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

from ...core.config import get_settings
from ...core.errors import ProviderUnavailable
from ...core.ffmpeg import run_ffmpeg
from .base import TTSProvider, TTSResult

DEFAULT_PYTHON = r"D:\studio-node\tts\vieneu\.venv\Scripts\python.exe"
DEFAULT_HF_HOME = r"D:\studio-node\hf"
RUNNER = Path(__file__).with_name("vieneu_runner.py")
LOAD_TIMEOUT_SEC = 600  # first start downloads the model (~1 GB)
REQUEST_TIMEOUT_SEC = 180


def _conf() -> dict:
    return dict(get_settings().get("tts.vieneu", {}) or {})


def _python() -> Path:
    return Path(os.environ.get("STUDIO_VIENEU_PYTHON") or _conf().get("python") or DEFAULT_PYTHON)


class _Runner:
    """The worker process; one per python path, shared by every provider instance."""

    def __init__(self, python: Path, binding: dict):
        env = {
            **os.environ,
            "HF_HOME": str(_conf().get("hf_home") or DEFAULT_HF_HOME),
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        self.proc = subprocess.Popen(
            [str(python), "-I", str(RUNNER), "--binding", json.dumps(binding)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.lock = threading.Lock()
        hello = self._read(LOAD_TIMEOUT_SEC)
        if not hello.get("ok"):
            self.close()
            raise ProviderUnavailable(f"VieNeu did not start: {hello.get('error')}", code="tts_unavailable")
        self.voices: list[str] = hello.get("voices", [])
        self.cuda = bool(hello.get("cuda"))

    def _read(self, timeout: float) -> dict:
        box: dict = {}

        def read() -> None:
            box["line"] = self.proc.stdout.readline()

        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(timeout)
        line = box.get("line")
        if not line:
            self.close()
            raise ProviderUnavailable("VieNeu worker stopped or timed out", code="tts_unavailable")
        return json.loads(line)

    def ask(self, req: dict) -> dict:
        with self.lock:
            if self.proc.poll() is not None:
                raise ProviderUnavailable("VieNeu worker is not running", code="tts_unavailable")
            self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            return self._read(REQUEST_TIMEOUT_SEC)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()


_runners: dict[tuple, _Runner] = {}


@atexit.register
def _close_all() -> None:
    for r in _runners.values():
        r.close()


def _runner(profile=None) -> _Runner:
    py = _python()
    binding = {
        k: profile.params[k]
        for k in ("model", "revision", "model_subfolder", "package_version")
        if profile and k in profile.params
    }
    key = (str(py), json.dumps(binding, sort_keys=True))
    r = _runners.get(key)
    if r is None or r.proc.poll() is not None:
        r = _runners[key] = _Runner(py, binding)
    return r


class VieneuTTS(TTSProvider):
    name = "vieneu"
    extension = ".wav"

    def check(self, profile):
        py = _python()
        if not py.is_file():
            return f"VieNeu venv not found ({py}) - run scripts/install_vieneu.ps1 on the GPU PC"
        return None

    def synthesize(self, text, profile, out_path):
        from ...core.voice_policy import assert_voice_allowed

        assert_voice_allowed(profile, self.registry.root if hasattr(self, "registry") else None)
        return self._generate(text, profile, out_path)

    def audition(self, text, profile, out_path):
        """Quarantined evaluation only; never a production fallback."""
        from ...core.voice_policy import assert_voice_allowed

        assert_voice_allowed(profile, self.registry.root, audition=True)
        return self._generate(text, profile, out_path)

    def _generate(self, text, profile, out_path):
        reason = self.check(profile)
        if reason:
            raise ProviderUnavailable(reason, code="tts_unavailable")
        p = profile.params
        seed = int(p.get("seed", int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)))  # same text -> same take
        resp = _runner(profile).ask(
            {
                "text": text,
                "voice": p.get("voice"),
                "out": str(out_path),
                "seed": seed,
                "temperature": float(p.get("temperature", 0.7)),
                "preset_sha256": p.get("preset_sha256"),
            }
        )
        if not resp.get("ok"):
            raise ProviderUnavailable(f"VieNeu failed: {resp.get('error')}", code="tts_unavailable")
        speed = float(p.get("speed", 1.0))
        if abs(speed - 1.0) > 1e-3:  # VieNeu has no pace control: time-stretch, pitch kept
            tmp = out_path.with_name(f"{out_path.stem}.speed{out_path.suffix}")
            run_ffmpeg(["-i", str(out_path), "-af", f"atempo={speed:.4f}", str(tmp)], stage="voice")
            tmp.replace(out_path)
        return TTSResult(out_path, None)  # no word timings: the voice stage aligns with faster-whisper
