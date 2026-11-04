"""OmniVoice in an isolated CUDA environment; reviewed production or quarantined audition."""

from __future__ import annotations

import atexit
import hashlib
import json
import math
import os
import subprocess
import threading
from pathlib import Path

from ...core.config import get_settings
from ...core.errors import ProviderUnavailable, ValidationError
from ...core.voice_policy import assert_voice_allowed
from .base import TTSProvider, TTSResult

DEFAULT_PYTHON = r"D:\studio-node\tts\omnivoice\.venv\Scripts\python.exe"
MODEL = "k2-fsa/OmniVoice"
REVISION = "c5fdb5ccb189668d56333f77ba2629f4cd7535f4"
RUNNER = Path(__file__).with_name("omnivoice_runner.py")
_workers = {}
_workers_lock = threading.Lock()


def _config():
    return dict(get_settings().get("tts.omnivoice", {}) or {})


class _Worker:
    def __init__(self, python, model, revision, hf_home, log):
        log.parent.mkdir(parents=True, exist_ok=True)
        self.stderr = log.open("a", encoding="utf-8")
        env = {**os.environ, "HF_HOME": hf_home, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        self.proc = subprocess.Popen(
            [str(python), "-I", str(RUNNER), "--model", model, "--revision", revision],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            encoding="utf-8",
            bufsize=1,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.lock = threading.Lock()
        hello = self.read(1200)
        if not hello.get("ok"):
            self.close()
            raise ProviderUnavailable(
                f"OmniVoice load failed: {hello.get('error')}; log: {log}", code="tts_unavailable"
            )

    def read(self, timeout):
        box = []
        thread = threading.Thread(target=lambda: box.append(self.proc.stdout.readline()), daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive() or not box or not box[0]:
            self.close()
            raise ProviderUnavailable(
                "OmniVoice worker stopped or timed out; inspect voices/candidates/omnivoice-worker.log",
                code="tts_unavailable",
            )
        return json.loads(box[0])

    def ask(self, req):
        with self.lock:
            self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            return self.read(300)

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self.stderr.close()


@atexit.register
def _close_all():
    for worker in _workers.values():
        worker.close()


def target_duration(text, params):
    """Match Vietnamese reference pacing using space-separated speech units, not English WPM."""
    rate = params.get("target_space_tokens_per_second")
    if rate is None:
        return None
    speed = float(params.get("speed", 1.0))
    rate = float(rate)
    if not math.isfinite(rate) or not 1 <= rate <= 12 or not math.isfinite(speed) or not 0.5 <= speed <= 2:
        raise ValidationError("Invalid speech rate or speed", code="voice_pacing")
    return max(0.5, len(text.split()) / (rate * speed))


class OmniVoiceTTS(TTSProvider):
    name = "omnivoice"
    extension = ".wav"

    def check(self, profile):
        python = Path(os.environ.get("STUDIO_OMNIVOICE_PYTHON") or _config().get("python") or DEFAULT_PYTHON)
        if not python.is_file():
            return "OmniVoice environment missing; run scripts/install_omnivoice.ps1"
        ref = self._reference(profile)
        if not ref.is_file():
            return f"OmniVoice reference missing: {ref}"
        if hashlib.sha256(ref.read_bytes()).hexdigest() != profile.params.get("ref_sha256"):
            return "OmniVoice reference changed; update its profile and audition again"
        return None

    def _reference(self, profile):
        ref = Path(profile.params.get("ref_audio", "__missing__"))
        return ref if ref.is_absolute() else self.registry.root / ref

    def synthesize(self, text, profile, out_path):
        assert_voice_allowed(profile, self.registry.root)
        return self._generate(text, profile, out_path)

    def audition(self, text, profile, out_path):
        assert_voice_allowed(profile, self.registry.root, audition=True)
        return self._generate(text, profile, out_path)

    def _generate(self, text, profile, out_path):
        reason = self.check(profile)
        if reason:
            raise ProviderUnavailable(reason, code="tts_unavailable")
        p = profile.params
        if not p.get("ref_text"):
            raise ValidationError("OmniVoice needs the verified reference transcript", code="voice_reference")
        conf = _config()
        python = os.environ.get("STUDIO_OMNIVOICE_PYTHON") or conf.get("python") or DEFAULT_PYTHON
        hf_home = str(conf.get("hf_home") or "D:/studio-node/hf")
        model, revision = p.get("model", MODEL), p.get("revision", REVISION)
        key = (python, model, revision, hf_home)
        with _workers_lock:
            worker = _workers.get(key)
            if worker is None or worker.proc.poll() is not None:
                worker = _workers[key] = _Worker(
                    python, model, revision, hf_home, self.registry.root / "candidates/omnivoice-worker.log"
                )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        resp = worker.ask(
            {
                "text": text,
                "voice": profile.id,
                "ref_audio": str(self._reference(profile).resolve()),
                "ref_text": p["ref_text"],
                "ref_sha256": p["ref_sha256"],
                "out": str(out_path.resolve()),
                "language": profile.lang,
                "speed": float(p.get("speed", 1.0)),
                "duration": target_duration(text, p),
                "num_step": int(p.get("num_step", 32)),
                "seed": int(p.get("seed", 42)),
            }
        )
        if not resp.get("ok"):
            raise ProviderUnavailable(f"OmniVoice failed: {resp.get('error')}", code="tts_unavailable")
        return TTSResult(out_path, None)
