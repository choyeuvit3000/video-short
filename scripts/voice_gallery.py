"""Build all distinct, non-blacklisted installed VieNeu auditions; never admit a voice."""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from studio.core.config import get_settings
from studio.core.ffmpeg import run_ffmpeg
from studio.core.media_probe import probe
from studio.core.voice_audition import audition_sample
from studio.core.voice_policy import blocked, signature
from studio.voices import load_registry

COMPARE_TEXT = (
    "Bạn có thể nối mình với một người lạ chỉ qua vài người quen. "
    "Trong thí nghiệm, những chuỗi thành công có trung bình năm phẩy hai người trung gian. "
    "Mình nhắc lại: năm phẩy hai người. Con số này chỉ tính những chuỗi đã đến đích. "
    "Nó không bảo đảm rằng ai cũng cách nhau đúng sáu bước. Còn năm trên mười là một nửa số điểm."
)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def slug(name):
    import re

    ascii_name = unicodedata.normalize("NFKD", name.replace("Đ", "D").replace("đ", "d"))
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.encode("ascii", "ignore").decode().lower()).strip("-")


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    reg = load_registry(settings)
    base = reg.get("vieneu-vi-short")
    date = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d")
    out = (args.out or settings.root / "output" / date / "voice_samples" / "vieneu_all").resolve()
    (out / "samples").mkdir(parents=True, exist_ok=True)
    (out / "cards").mkdir(exist_ok=True)
    env = Path(settings.get("tts.vieneu.python")).parent.parent / "Lib/site-packages/vieneu/assets/voices_v3_turbo.json"
    presets = json.loads(env.read_text(encoding="utf-8"))["presets"]
    banned_refs = [v.get("codes") for n, v in presets.items() if blocked("vieneu", n, {"voice": n})]
    excluded = []
    inventory = []
    for name, spec in presets.items():
        if (
            blocked("vieneu", name, {"voice": name})
            or any(blocked("vieneu", alias, {"voice": alias}) for alias in spec.get("aliases", []))
            or any(spec.get("codes") == ref for ref in banned_refs)
        ):
            excluded.append(name)
        else:
            inventory.append((name, spec))
    inventory.sort(
        key=lambda row: (
            row[1].get("gender") != "male",
            {"Nam": 0, "Trung": 1, "Bắc": 2}.get(row[1].get("region"), 3),
            row[0] == "Minh Triết",
            row[0],
        )
    )
    prior = reg.root / "candidates/vieneu-vi-short/audition.json"
    old_meta = json.loads(prior.read_text(encoding="utf-8")) if prior.is_file() else {}
    text = COMPARE_TEXT
    manifest = {
        "status": "GENERATING",
        "model": base.params["model"],
        "revision": base.params["revision"],
        "text": text,
        "excluded": excluded,
        "voices": [],
        "failures": [],
        "human_approval": "PENDING",
        "previous_voice_rejected": "Minh Triết",
    }
    write(out / "manifest.json", manifest)
    for index, (name, spec) in enumerate(inventory, 1):
        try:
            ident = "vieneu-gallery-" + slug(name)
            params = {
                **base.params,
                "voice": name,
                "preset_sha256": hashlib.sha256(
                    json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest(),
            }
            p = replace(base, id=ident, status="experimental", params=params, estimated_space_tokens_per_second=None)
            if (
                name == base.params["voice"]
                and old_meta.get("voice_signature") == signature(base)
                and old_meta.get("text") == text
                and sha(reg.root / "candidates/vieneu-vi-short/audition.wav") == old_meta["sha256"]
            ):
                p = base
                raw = reg.root / "candidates/vieneu-vi-short/audition.wav"
            else:
                raw = audition_sample(reg, p, text)
            normalized = out / "samples" / (slug(name) + ".mp3")
            meta_path = normalized.with_suffix(".json")
            current = {"raw_sha256": sha(raw), "voice_signature": signature(p), "normalization": "lufs16-v1"}
            cached = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
            if not (
                normalized.is_file()
                and all(cached.get(k) == v for k, v in current.items())
                and cached.get("sha256") == sha(normalized)
            ):
                measurement = run_ffmpeg(
                    ["-i", str(raw), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                    stage="audition",
                    loglevel="info",
                )
                levels = json.loads(measurement[measurement.rfind("{") : measurement.rfind("}") + 1])
                norm = (
                    "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:"
                    f"measured_I={levels['input_i']}:measured_TP={levels['input_tp']}:"
                    f"measured_LRA={levels['input_lra']}:measured_thresh={levels['input_thresh']}:"
                    f"offset={levels['target_offset']}"
                )
                run_ffmpeg(
                    ["-i", str(raw), "-af", norm, "-ar", "48000", "-ac", "2", "-b:a", "192k", str(normalized)],
                    stage="audition",
                )
                write(meta_path, {**current, "sha256": sha(normalized)})
            info = probe(normalized)
            if info.duration < 3 or info.sample_rate != 48000:
                raise RuntimeError("Invalid audio sample")
            profile_data = {k: v for k, v in asdict(p).items() if k != "source_file"}
            profile_data["estimated_space_tokens_per_second"] = round(len(text.split()) / probe(raw).duration, 2)
            entry = {
                "index": index,
                "name": name,
                "gender": spec.get("gender"),
                "region": spec.get("region"),
                "description": spec.get("description", ""),
                "aliases": spec.get("aliases", []),
                "file": normalized.relative_to(out).as_posix(),
                "duration": round(info.duration, 3),
                "sha256": sha(normalized),
                "raw_file": str(raw.resolve()),
                "raw_sha256": sha(raw),
                "profile": profile_data,
                "voice_signature": signature(p),
                "human_approval": "PENDING",
            }
            manifest["voices"].append(entry)
            write(out / "manifest.json", manifest)
            print(f"READY {index}/{len(inventory)} {name}: {info.duration:.2f}s", flush=True)
        except Exception as exc:
            manifest["failures"].append({"name": name, "error": str(exc)})
            write(out / "manifest.json", manifest)
            print(f"FAILED {name}: {exc}", flush=True)
    manifest["status"] = "SAMPLES_READY" if not manifest["failures"] else "PARTIAL"
    write(out / "manifest.json", manifest)
    (out / "script.txt").write_text(text, encoding="utf-8")
    if not manifest["failures"]:
        from voice_gallery_page import build

        build(out)
    print(str(out), flush=True)
    return 1 if manifest["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
