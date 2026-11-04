"""Bridge to the existing VieNeu installation without modifying it."""
import atexit
import json
import os
import subprocess
import threading
from pathlib import Path

_proc = None
_lock = threading.Lock()
_key = None

def close():
    global _proc
    if _proc and _proc.poll() is None:
        _proc.kill()
        _proc.wait()
    _proc = None

atexit.register(close)

def _read(timeout):
    lines = []
    thread = threading.Thread(target=lambda: lines.append(_proc.stdout.readline()), daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive() or not lines or not lines[0]:
        close()
        raise RuntimeError('VieNeu worker stopped or timed out')
    result = json.loads(lines[0])
    if not result.get('ok'):
        raise RuntimeError(result.get('error', 'VieNeu failed'))
    return result

def generate(text: str, wav: Path, cfg: dict):
    global _proc, _key
    from ..core.voice_policy import assert_social_config
    assert_social_config({"engines":["vieneu"],"vieneu":cfg})
    key = (cfg['python'], cfg['runner'], cfg['hf_home'])
    with _lock:
        if _proc is None or _proc.poll() is not None or key != _key:
            close()
            env = {**os.environ, 'HF_HOME': cfg['hf_home'], 'HF_HUB_OFFLINE': '1',
                   'PYTHONIOENCODING': 'utf-8'}
            _proc = subprocess.Popen([cfg['python'], '-I', cfg['runner']],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='utf-8', env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            _key = key
            _read(600)
        _proc.stdin.write(json.dumps({'text': text, 'voice': cfg.get('voice'),
            'out': str(wav.resolve()), 'seed': 42, 'temperature': cfg.get('temperature', .7)},
            ensure_ascii=False) + '\n')
        _proc.stdin.flush()
        _read(180)
