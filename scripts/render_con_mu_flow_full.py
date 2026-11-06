"""Render the requested complete hybrid Cồn Mù film from existing approved speech and visual media."""

from pathlib import Path

from studio.core.outputs import organized_output
from studio.core.user_review import require
from studio.social_video.hybrid_full import render_hybrid
from studio.social_video.illustrated_full import frame_shots
from studio.social_video.quality import sha256
from studio.social_video.util import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "projects/social_video/work/reddit/original_con_mu_20261105_v3"
TRIAL = ROOT / "projects/flow_trials/con_mu_20261106"
WORK = FOLDER / "work/flow_full_hybrid_20261106"
BASELINE = FOLDER / "work/motion_stability_v1/storyboard.json"
SOURCE = ROOT / "output/2026-11-05/original_story_full/original_story_full__original_con_mu_20261105_v3.mp4"


def main():
    WORK.mkdir(exist_ok=True)
    state = WORK / "output_location.json"
    if not state.exists():
        write_json(state, {"date": "2026-11-06", "mode": "original_story_full"})
    out = organized_output(ROOT / "output", "original_story_full", state)
    final = out / "original_story_full__original_con_mu_20261105_v3__flow_hybrid.mp4"
    base = read_json(BASELINE)
    shots = frame_shots(base["shots"], base["duration_seconds"])
    scene8 = next(x for x in shots if x["shot"] == 8)
    imports = read_json(TRIAL / "work/flow_imports.json")
    corrected = TRIAL / "images/scene_03_fullbody.png"
    plan = {
        "version": 1,
        "user_request": "làm toàn bộ video hoàn chỉnh xem sao",
        "hybrid_selection_message": (
            "Kết hợp: clip AI ở các cảnh chính, minh họa chuyển động ở các cảnh còn lại để giảm số lần gen"),
        "scope": "complete_story_visual_revision_only",
        "accepted_final_fingerprint": require(FOLDER, "final")["fingerprint"],
        "voice_fingerprint": require(FOLDER, "voice")["fingerprint"],
        "script_sha256": sha256(FOLDER / "vi.json"),
        "source_video": str(SOURCE), "source_video_sha256": sha256(SOURCE),
        "baseline_plan": str(BASELINE), "baseline_plan_sha256": sha256(BASELINE),
        "duration_seconds": base["duration_seconds"], "voice": "Ngọc Huyền", "speech_speed": 1.25,
        "output": str(final), "new_generation_calls": 0, "new_human_approval_created": False,
        "replacements": [
            {"shot": 1, "clip_path": str(TRIAL / "clips/scene_01.mp4"),
             "clip_sha256": imports["scene_01"]["sha256"], "still_prefix_frames": 0,
             "reason": "Hạnh raises her head in the opening hook; trim the clip to the existing scene."},
            {"shot": 3, "clip_path": str(TRIAL / "clips/scene_02.mp4"),
             "clip_sha256": imports["scene_02"]["sha256"], "still_prefix_frames": 0,
             "allow_video_retime": True,
             "reason": "Small visual-only slowdown covers this short sandal detail; speech is never retimed."},
            {"shot": 8, "clip_path": str(TRIAL / "clips/scene_03.mp4"),
             "clip_sha256": imports["scene_03"]["sha256"], "still_prefix_frames": scene8["frames"] - 238,
             "still_path": str(corrected), "still_sha256": sha256(corrected),
             "reason": "Corrected full-body image zooms out into the matching fixed-camera pointing action."},
        ],
    }
    path = WORK / "hybrid_plan.json"
    write_json(path, plan)
    write_json(WORK / "preflight.json", {
        "scope": "hybrid_visual_revision", "scene_count": len(shots), "replaced_scenes": [1, 3, 8],
        "new_model_generation_calls": 0, "new_tts_calls": 0, "prior_voice_reused": True,
        "creator_request_recorded": True, "preserve_existing_three_approval_events": True,
        "source_mix": "Exact approved AAC, including narration, BGM and SFX",
        "note": "Renderer validates review/script/media hashes before render, and compares AAC and PCM afterward."})
    print(render_hybrid(FOLDER, path), flush=True)


if __name__ == "__main__":
    main()
