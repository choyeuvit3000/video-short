"""Three user-owned, hash-bound production checkpoints. Never inherited from agent review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import speech_edit
from .errors import ManualGateRequired, ValidationError

STAGES = ("script", "voice", "final")


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sha(path):
    if not path.is_file():
        raise ValidationError(f"Thiếu tệp trong gói duyệt: {path}", code="review_missing_file")
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def waiver(folder, stage):
    """A creator can explicitly waive checkpoints for a named project/batch.

    This is prospective authorization to work, never a claim they heard or saw an
    artifact which did not exist. Technical/content validation still runs below.
    """
    folder = Path(folder).resolve()
    data = read(folder / "review_waiver.json", {})
    if (
        data.get("reviewer") == "user"
        and data.get("project_id") == folder.name
        and data.get("message", "").strip()
        and stage in data.get("stages", [])
    ):
        return data
    return None


def payload(folder, stage):
    folder = Path(folder).resolve()
    if stage == "script":
        p = read(folder / "project.json", {})
        if p:
            data = {k: p.get(k) for k in ("workflow", "title", "language", "source", "video")}
            data["scenes"] = [
                {k: s.get(k) for k in ("scene_id", "narration", "duration_sec", "visual")} for s in p.get("scenes", [])
            ]
            data["decisions"] = {
                k: v for k, v in p.get("options", {}).items() if k not in ("reviewed", "image_credits")
            }
        else:
            data = {
                "vi": read(folder / "vi.json", {}),
                "posts": read(folder / "posts.json", []),
                "plan": read(folder / "merged_plan.json", {}),
            }
            if (folder / "source.json").is_file():
                data["source"] = read(folder / "source.json")
        data["brief"] = {
            k: v
            for k, v in read(folder / "video_brief.json", {}).get("answers", {}).items()
            if k not in ("voice", "pacing", "speech_speed")
        }
        if not p:
            from ..social_video.util import load_config

            cfg = load_config()
            data["reddit_choices"] = {
                k: cfg["reddit"].get(k)
                for k in (
                    "part_max_sec",
                    "part_target_sec",
                    "voice_profile",
                    "speech_speed",
                    "narration_speed",
                    "export_full",
                    "caption_mode",
                    "phrase_words",
                    "card_max_lines",
                    "background_family",
                    "vignette_opacity",
                    "music_relative_db",
                    "story_sfx_enabled",
                )
            }

        return data
    require(folder, "script")
    if stage == "voice":
        p = read(folder / "project.json", {})
        files = []
        if p:
            files = [folder / s["audio_path"] for s in p.get("scenes", []) if s.get("audio_path")]
            spoken = [s for s in p.get("scenes", []) if s.get("narration")]
            has_spoken = bool(spoken)
            if len(files) != len(spoken):
                raise ValidationError("Cần lời đọc cho toàn bộ cảnh", code="review_missing_voice")
            files += [folder / "work/timeline.json"] + sorted((folder / "subtitles").glob("*.words.json"))
        else:
            manifest = read(folder / "voice_manifest.json", {})
            has_spoken = bool(read(folder / "vi.json", {}).get("paragraphs")) or any(
                b.get("narration", "").strip() for b in read(folder / "merged_plan.json", {}).get("beats", [])
            )
            if not manifest:
                raise ValidationError("Chuẩn bị gói nghe/xem trước bằng social-voice", code="review_missing_voice")
            if has_spoken and (folder / "vi.json").is_file() and not manifest.get("body"):
                raise ValidationError("Cần gói lời đọc Reddit có danh sách câu đã nghe", code="review_missing_voice")
            files = [Path(x) for x in manifest.get("files", [])]
            files += [Path(x) for x in manifest.get("timing_files", [])]
            files += [Path(x) for x in manifest.get("ending_timing_files", [])]
            if (folder / "part_plan.json").is_file():
                files.append(folder / "part_plan.json")
        if has_spoken and (not files or not any(x.suffix.lower() in (".wav", ".mp3") for x in files)):
            raise ValidationError("Chưa có toàn bộ lời đọc để người dùng nghe duyệt", code="review_missing_voice")
        if p:
            for scene in p.get("scenes", []):
                v = scene.get("visual", {})
                for k in ("file", "path", "overlay"):
                    if v.get(k) and not str(v[k]).startswith("asset:"):
                        candidate = folder / v[k]
                        if candidate.is_file():
                            files.append(candidate)
            from ..voices import load_registry
            from .config import get_settings
            from .voice_policy import signature

            settings = get_settings()
            choices = dict(p.get("audio", {}))
            if choices.get("source") != "manual":
                registry = load_registry(settings)
                profile = (
                    registry.get(choices["voice_profile"])
                    if choices.get("voice_profile")
                    else registry.default_for(
                        p.get("language", "vi"), p.get("workflow"), p.get("video", {}).get("format")
                    )
                )
                choices["profile_signature"] = signature(profile)
            style_name = p.get("video", {}).get("caption_style", "clean_box")
            style_path = settings.path("assets") / "shared/caption_styles" / (style_name + ".yaml")
            if style_path.is_file():
                files.append(style_path)
        else:
            from ..social_video.util import load_config
            from .creative_brief import apply_social
            from .voice_policy import signature, social_profile

            config = load_config()
            apply_social(folder, config)
            choices = {k: config.get(k) for k in ("tts", "reddit", "story", "video", "fonts", "bgm")}
            choices["profile_signature"] = signature(social_profile(config["tts"])[0])
            expected = digest({"tts": config["tts"], "narration_speed": config["reddit"].get("narration_speed", 1.1)})
            if (
                manifest.get("production_choices") != expected
                or manifest.get("voice_signature") != choices["profile_signature"]
            ):
                raise ValidationError(
                    "Cấu hình giọng đã đổi; chuẩn bị lại lời đọc trước khi duyệt", code="review_voice_stale"
                )
        if (folder / "voice_manifest.json").is_file():
            files.append(folder / "voice_manifest.json")
        if (folder / "continuous_voice.json").is_file():
            files.append(folder / "continuous_voice.json")
            files += [Path(x["path"]) for x in read(folder / "continuous_voice.json").get("files", [])]
        if (folder / "named_voice_authorization.json").is_file():
            files.append(folder / "named_voice_authorization.json")
        files += sorted(
            x
            for x in (folder / "work/previews").rglob("*")
            if x.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".wav", ".mp3", ".m4a"}
        )
        files += sorted((folder / "work/speech_checks").glob("*.json"))
        if (folder / "background_plan.json").is_file():
            files.append(folder / "background_plan.json")
            files += [Path(x["source"]) for x in read(folder / "background_plan.json", {}).get("slots", {}).values()]
        if (folder / "scene_plan.json").is_file():
            files.append(folder / "scene_plan.json")
            files += [Path(x["path"]) for x in read(folder / "scene_plan.json", {}).values()]
        if (folder / "sound_plan.json").is_file():
            files += [
                Path(__file__).parents[1] / "social_video" / name
                for name in (
                    "story_cards.py",
                    "story_sound.py",
                    "story_preview.py",
                    "story_scenes.py",
                    "reddit.py",
                    "reddit_full.py",
                )
            ]
            files.append(folder / "sound_plan.json")
            files += [Path(x["path"]) for x in read(folder / "sound_plan.json", {}).get("assets", [])]
        from .speech_checks import critical_numbers, file_sha, text_sha

        if p:
            samples = [
                (s["scene_id"], s.get("narration", ""), folder / s["audio_path"])
                for s in p.get("scenes", [])
                if s.get("audio_path")
            ]
        elif (folder / "vi.json").is_file():
            from ..social_video.reddit import chunks

            texts = [s for group in chunks(read(folder / "vi.json")["paragraphs"]) for s in group]
            if len(texts) != len(manifest.get("body", [])):
                raise ValidationError("Thiếu tệp lời đọc Reddit theo từng câu", code="review_missing_voice")
            samples = [
                (f"reddit_{i:04d}", t, Path(a["path"]))
                for i, (t, a) in enumerate(zip(texts, manifest["body"], strict=True))
            ]
        else:
            samples = []
            for i, beat in enumerate(read(folder / "merged_plan.json", {}).get("beats", [])):
                if not beat.get("narration", "").strip():
                    continue
                asset = manifest.get("beats", {}).get(str(i))
                if not asset:
                    raise ValidationError("Thiếu tệp lời đọc cho bài Threads", code="review_missing_voice")
                samples.append((f"merged_b{i:02d}", beat["narration"], Path(asset["audio"])))
        for scene_id, text, audio in samples:
            if not critical_numbers(text):
                continue
            check = read(folder / "work/speech_checks" / (scene_id + ".json"), {})
            if check.get("audio_sha256") != file_sha(audio) or check.get("text_sha256") != text_sha(text):
                raise ValidationError("Cần kiểm tra lại cách đọc số từ tệp tiếng thật", code="review_number_check")
        return {
            "script": digest(payload(folder, "script")),
            "voice_choices": choices,
            "files": [{"path": str(x.resolve()), "sha256": sha(x)} for x in files],
        }
    if stage == "final":
        require(folder, "voice")
        if (folder / "project.json").is_file():
            from .project import ProjectContext

            ctx = ProjectContext(folder)
            outputs = [ctx.final_video]
        else:
            outputs = [Path(x["path"]) for x in read(folder / "native_render_cache.json", {}).get("outputs", [])]
        if not outputs or not all(x.is_file() for x in outputs):
            raise ValidationError("Chưa có video để duyệt", code="review_missing_final")
        for video in outputs:
            qpath = (
                ctx.result_path("qc_report.json")
                if (folder / "project.json").is_file()
                else video.with_suffix(".qc.json")
            )
            qc = read(qpath, {})
            if qc.get("errors") or qc.get("automatic", qc.get("status")) != "PASS" or qc.get("sha256") != sha(video):
                raise ValidationError("Video chưa qua kiểm tra kỹ thuật", code="review_qc")
        return {
            "voice": digest(payload(folder, "voice")),
            "videos": [
                {
                    "path": str(x.resolve()),
                    "sha256": sha(x),
                    "qc_path": str(
                        ctx.result_path("qc_report.json")
                        if (folder / "project.json").is_file()
                        else x.with_suffix(".qc.json")
                    ),
                }
                for x in outputs
            ],
        }
    raise ValidationError("Chọn script, voice hoặc final", code="review_stage")


def script_issues(folder):
    p = read(folder / "project.json", {})
    texts = (
        [s.get("narration", "") for s in p.get("scenes", [])]
        if p
        else read(folder / "vi.json", {}).get("paragraphs", [])
    )
    if not p:
        vi = read(folder / "vi.json", {})
        texts = texts + ([vi["hook"]] if vi.get("hook") else []) + vi.get("part_hooks", [])
    if not p and not texts:
        texts = [b.get("narration", "") for b in read(folder / "merged_plan.json", {}).get("beats", [])]
    result = [{"line": i + 1, "issue": issue} for i, t in enumerate(texts) for issue in speech_edit.issues(t)]
    if (folder / "vi.json").is_file() and "character_map" not in read(folder / "vi.json", {}):
        result.append(
            {"line": 0, "issue": "Cần rà và khai báo character_map cho toàn truyện; để {} nếu không có tên cần đổi."}
        )
    return result


def prepare(folder, stage):
    folder = Path(folder).resolve()
    if stage == "script":
        speech_edit.project_edit(folder)
        from .creative_brief import apply_project_choices
        from .creative_brief import prepare as brief_prepare

        brief_prepare(folder)
        apply_project_choices(folder)
    data = payload(folder, stage)
    key = digest(data)
    if stage == "script" and (folder / "project.json").is_file():
        ledger = read(folder / "user_reviews.json", {"approvals": []})
        accepted = any(
            x.get("stage") == "script" and x.get("fingerprint") == key and x.get("reviewer") == "user"
            for x in ledger["approvals"]
        )
        p = read(folder / "project.json")
        p.setdefault("options", {})["reviewed"] = accepted
        write(folder / "project.json", p)
    packet = {
        "stage": stage,
        "fingerprint": key,
        "payload": data,
        "issues": script_issues(folder) if stage == "script" else [],
        "status": "USER_REVIEW_WAIVED" if waiver(folder, stage) else "WAITING_USER",
        "editable": (
            "Sửa project.json/vi.json và chuẩn bị lại gói; "
            "duyệt gói đang hiển thị bằng phản hồi của chính người tạo video."
        ),
    }
    write(folder / f"review_{stage}.json", packet)
    lines = [
        f"# Duyệt {STAGES.index(stage) + 1}/3: "
        + {"script": "Kịch bản và lựa chọn dựng", "voice": "Nghe lời đọc và xem bố cục", "final": "Video hoàn chỉnh"}[
            stage
        ],
        "",
        f"Mã bản cần duyệt: {key}",
        "",
        (
            "Người dùng đã yêu cầu tự hoàn tất đợt này; không ghi nhận là đã nghe/xem tệp chưa tồn tại."
            if waiver(folder, stage)
            else "Chỉ người dùng được duyệt. Agent không tự duyệt thay."
        ),
        "",
    ]
    if stage == "script":
        p = read(folder / "project.json", {})
        texts = (
            [s.get("narration", "") for s in p.get("scenes", [])]
            if p
            else read(folder / "vi.json", {}).get("paragraphs", [])
        )
        lines += [f"{i + 1}. {t}" for i, t in enumerate(texts)]
        if not p:
            vi = read(folder / "vi.json", {})
            if not texts:
                texts = [b.get("narration", "") for b in data.get("plan", {}).get("beats", [])]
                lines += [f"{i + 1}. {t}" for i, t in enumerate(texts)]
            lines += [
                "",
                "## Câu mở đầu và bảng tên",
                json.dumps(
                    {k: vi.get(k) for k in ("hook", "part_hooks", "character_map", "speech_lexicon")},
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        lines += [
            "",
            "## Các lựa chọn đi cùng lần duyệt",
            json.dumps(
                {
                    "brief": data.get("brief", {}),
                    "video": data.get("video"),
                    "decisions": data.get("decisions", data.get("reddit_choices")),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "",
            "## Điểm cần sửa",
            json.dumps(packet["issues"], ensure_ascii=False, indent=2),
        ]
    else:
        if stage == "voice":
            lines += [
                "## Tệp cần nghe/xem",
                "",
                "Nghe toàn bộ các tệp theo thứ tự; báo câu/từ cần sửa trước khi duyệt.",
                "",
            ]
            for item in data["files"]:
                path = Path(item["path"])
                if path.suffix.lower() in (".mp3", ".wav", ".m4a", ".mp4", ".png", ".jpg", ".jpeg", ".webp"):
                    lines += [f"![{path.name}]({path.as_posix()})", ""]
                if path.parent.name == "speech_checks":
                    report = read(path, {})
                    phrases = [c["phrase"] for c in report.get("checks", []) if c.get("phrase")]
                    if phrases:
                        lines += [
                            "Cụm cần nghe kỹ: " + "; ".join(phrases),
                            "ASR nguyên gốc: " + report.get("raw_transcript", ""),
                            "",
                        ]
        else:
            for item in data["videos"]:
                lines += [f"![Video cần duyệt]({Path(item['path']).as_posix()})", ""]
        lines += [json.dumps(data, ensure_ascii=False, indent=2)]
    (folder / f"REVIEW_{stage.upper()}.md").write_text("\n".join(lines), encoding="utf-8")
    return packet


def require(folder, stage):
    folder = Path(folder).resolve()
    ledger = read(folder / "user_reviews.json", {"approvals": []})
    found = next((x for x in reversed(ledger["approvals"]) if x["stage"] == stage), None)
    # Prior stages must remain valid, even if a later audio/video is cached.
    if stage != "script":
        require(folder, STAGES[STAGES.index(stage) - 1])
    authorization = waiver(folder, stage)
    if authorization:
        if stage == "script" and script_issues(folder):
            raise ValidationError("Sửa lỗi kịch bản trước khi tự hoàn tất", code="review_script_issues")
        # payload validates actual narration assets, source/voice identity, number
        # audits and final QC; waiving a human checkpoint cannot bypass those.
        current = payload(folder, stage)
        return {
            "stage": stage,
            "reviewer": "user",
            "message": authorization["message"],
            "authorization": "USER_WAIVED_CHECKPOINT",
            "fingerprint": digest(current),
        }
    current = digest(payload(folder, stage)) if found else None
    if not found or found.get("fingerprint") != current or found.get("reviewer") != "user":
        raise ManualGateRequired(
            "user_" + stage,
            f"Chờ người dùng sửa/duyệt mốc {STAGES.index(stage) + 1}/3 ({stage}). "
            f"Đọc REVIEW_{stage.upper()}.md và review_{stage}.json. "
            "Agent/Codex không được tự cấp duyệt; --force và cache không bỏ qua bước này.",
        )
    return found


def checkpoint(folder, stage):
    """Produce a concrete packet before stopping; never record an acceptance."""
    if stage != "script":
        checkpoint(folder, STAGES[STAGES.index(stage) - 1])
    try:
        return require(folder, stage)
    except ManualGateRequired:
        prepare(folder, stage)
        return require(folder, stage)


def approve(folder, stage, message):
    folder = Path(folder).resolve()
    if not message.strip():
        raise ValidationError("Cần phản hồi duyệt thực tế của người dùng", code="review_user_message")
    packet = read(folder / f"review_{stage}.json", {})
    current = payload(folder, stage)
    key = digest(current)
    if packet.get("fingerprint") != key:
        raise ValidationError("Gói duyệt đã thay đổi; chuẩn bị và xem lại trước khi duyệt", code="review_stale")
    if stage == "script" and script_issues(folder):
        raise ValidationError("Sửa số/tên chưa chuẩn hóa trước khi duyệt", code="review_script_issues")
    if stage == "script":
        from .creative_brief import prepare as prepare_brief

        if prepare_brief(folder)["missing"]:
            raise ValidationError("Cần chốt mục tiêu và người xem trong brief trước khi duyệt", code="brief_incomplete")
    ledger = read(folder / "user_reviews.json", {"approvals": [], "max_approvals": 3})
    if any(x["stage"] == stage and x["fingerprint"] == key for x in ledger["approvals"]):
        return require(folder, stage)
    if len(ledger["approvals"]) >= 3:
        raise ManualGateRequired(
            "review_budget",
            "Đã dùng ba lần duyệt cho video. Dừng để người dùng quyết định; "
            "không tự mở thêm lượt hay tự thông qua bản thay đổi.",
        )
    item = {
        "stage": stage,
        "reviewer": "user",
        "message": message,
        "fingerprint": key,
        "approval_number": len(ledger["approvals"]) + 1,
    }
    ledger["approvals"].append(item)
    write(folder / "user_reviews.json", ledger)
    if stage == "script":
        p = read(folder / "project.json", {})
        if p:
            p.setdefault("options", {})["reviewed"] = True
            write(folder / "project.json", p)
        from .creative_brief import approve as approve_brief

        approve_brief(folder, "user")
    if stage == "final":
        for video in current["videos"]:
            qpath = Path(video["qc_path"])
            q = read(qpath, {})
            q.update(status="PASS", editorial="APPROVED", reviewer="user", review_note=message, sha256=video["sha256"])
            write(qpath, q)
    return item


def revise_voice_choice(folder, message):
    """A user's replacement choice revises checkpoint two before final acceptance.

    Keep the superseded version and exact messages; this is neither a new stage
    nor a reset of the three-checkpoint ledger or a claim of listening.
    """
    folder = Path(folder).resolve()
    if not message.strip():
        raise ValidationError("Cần chỉ dẫn đổi giọng thực tế", code="review_user_message")
    require(folder, "script")
    ledger = read(folder / "user_reviews.json", {"approvals": []})
    if any(item["stage"] == "final" for item in ledger["approvals"]):
        raise ManualGateRequired("review_revision", "Bản cuối đã được duyệt; cần phạm vi sửa mới.")
    previous = next((item for item in reversed(ledger["approvals"]) if item["stage"] == "voice"), None)
    if previous is None:
        return approve(folder, "voice", message)
    current = payload(folder, "voice")
    fingerprint = digest(current)
    packet = read(folder / "review_voice.json", {})
    if packet.get("fingerprint") != fingerprint:
        raise ValidationError("Chuẩn bị gói giọng mới trước khi ghi lựa chọn", code="review_stale")
    if previous.get("fingerprint") == fingerprint and previous.get("message") == message:
        return previous
    history = list(previous.get("revisions", []))
    history.append({k: v for k, v in previous.items() if k != "revisions"})
    updated = {
        "stage": "voice",
        "reviewer": "user",
        "message": message,
        "fingerprint": fingerprint,
        "approval_number": previous["approval_number"],
        "revisions": history,
        "scope": "Explicit replacement voice choice for the already-approved script, before final acceptance",
        "all_parts_listened_by_user": False,
    }
    ledger["approvals"][ledger["approvals"].index(previous)] = updated
    write(folder / "user_reviews.json", ledger)
    return updated
