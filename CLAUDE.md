# CLAUDE.md — video-short (AI Shorts Studio v2)

The user writes in Vietnamese: answer in Vietnamese, keep code/comments/identifiers in English.

## What this is
A Windows-first CLI (`studio`) that builds short (9:16) and long (16:9) videos through **workflow recipes**.
Existing tools do the work (FFmpeg, Pillow, edge-tts/Piper, faster-whisper); AI CLIs (`claude -p`, `agy -p`,
`codex exec`) only write scripts/storyboards; web-only AI steps (ChatGPT images, Google Flow clips) are
**manual gates**. Two machines: this laptop = controller; a home PC with RTX 3080 10 GB = GPU node running
`studio worker serve` (FastAPI + SQLite queue) inside its schedule; the laptop submits jobs over Tailscale.

If you are running on the **GPU PC**, your task is probably `docs/SETUP_GPU_NODE.md` — follow it step by step.

## Commands
```powershell
uv venv --python 3.11 .venv ; uv pip install -e ".[piper,align,dev]"     # laptop  (GPU PC: ".[gpu,dev]")
.\.venv\Scripts\python.exe -m pytest -q          # needs ffmpeg on PATH or $env:STUDIO_FFMPEG_DIR, else ffmpeg tests skip
.\.venv\Scripts\ruff.exe check .                 # line-length 120
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_windows.ps1    # 3 real renders, --strict
powershell -ExecutionPolicy Bypass -File .\scripts\demo_videos.ps1          # 2 demo videos (edge voice, manual gate)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_worker_local.ps1    # worker over real HTTP, 127.0.0.1
studio doctor [--gpu]
```
Set `$env:PYTHONIOENCODING="utf-8"` when piping output that contains Vietnamese.

## Layout
- `src/studio/core/` — schema (project.json v2 + v1 upgrade), config (studio.yaml + local.yaml + .env), paths
  (`resolve_inside` refuses traversal/absolute), ffmpeg (arg lists only), media_probe, subtitles (SRT/ASS,
  word highlight), validator, qc, cost ledger, cache, logging, errors (exit codes).
- `src/studio/pipeline/` — `runner.py` (stages, state.json, manual gate → TODO_MANUAL.md + exit 3), `voice.py`
  (TTS + alignment + timeline.json), `fingerprint.py` (render/qc/package skipped when inputs + outputs unchanged;
  bump `REV` when their output changes for the same inputs).
- `src/studio/renderers/render.py` — per-scene segments (cached via `.key`, bump `SEGMENT_REV`) → concat →
  audio mix/ducking + loudnorm → captions (margins inside `safe_zone`) → previous final to `output/history/`
  (`core/outputs.py`) → atomic final. `core/qc_analysis.py`: loudness/silence/black/freeze + caption safe zone.
- `src/studio/renderers/manim_render.py` — visual type `manim`: pydantic param models per template, spec JSON
  (`STUDIO_MANIM_SPEC`), `python -m manim render` subprocess, cached via `core/cache.build_cached` (bump `MANIM_REV`).
  `renderers/manim_scenes/templates.py` is standalone (runs inside manim, never imported by studio — importing
  manim in-process hijacks logging). Custom scenes: `visual.file` + `scene_class`, user-written only.
- `src/studio/providers/` — `llm/` (claude/agy/codex CLIs + manual), `tts/` (edge, piper, mock, paid adapters
  disabled), `align.py` (provider words → faster-whisper → estimate), `source/` (text file, URL, Reddit OAuth,
  Threads API). `renderers/card.py` draws the post card; `voices.py` loads the voice registry.
- `src/studio/workflows/` — stage functions per workflow (`story_reader.py`, `ai_cinematic.py`, `knowledge.py`,
  `common.py`); `topics.py` loads topic packs `workflows/_shared/topics/<id>.yaml` (science, history, finance...);
  recipes live in `workflows/<name>/workflow.yaml` (stages, defaults, format_overrides, llm_chain) + prompts.
- `voices/` — registry + profile YAMLs; models in `voices/local/models/` (gitignored, per machine).
- `config/nodes.yaml` — worker nodes (tokens only via `token_env` → `.env`); `config/local.yaml` patches by id.
- `src/studio/nodes/` — controller side: node registry + schedule + `select_node`, `bundle.py` (sha256
  manifests, hash cache, apply results without clobbering local edits → `*.remote.*`), `client.py` (httpx),
  `remote.py` (submit / wait / pull; `REMOTE_STAGES` = validate voice render qc package).
- `src/studio/worker/` — GPU PC side: `app.py` (FastAPI, Bearer token, `extra="forbid"` models, only job type
  `pipeline`), `queue.py` (SQLite), `store.py` (blob store by sha256), `jobs.py` (materialize project + run
  stages), `service.py` (schedule / user-idle / GPU-busy policy, loop). Install: `scripts/install_worker.ps1`.

## Invariants (do not break)
1. Never overwrite, move or delete user input media (`clips/`, `images/`, `source/`, `audio/` given by user).
   Generated files go to `work/` and `output/` only; final video is written to a temp file then renamed.
2. Every subprocess call uses an argument list — never `shell=True`. Paths with spaces + Vietnamese must work.
3. Errors carry `code` and `scene_id` when scene-specific; exit codes: 0 ok, 1 error, 2 validation,
   3 waiting_manual, 4 budget, 5 QC fail, 6 waiting_node. Never report success without a probed, valid output file.
4. AI never writes code that runs: knowledge scenes are templates + validated JSON params. `3b1b/videos` is
   CC BY-NC-SA — reference only, never copy its code. Engine is ManimCE (MIT), not ManimGL.
5. No browser automation, scraping, cookie/session capture or quota bypass of Claude/ChatGPT/Flow/etc.
   Content comes from official APIs or text the user pastes.
6. Secrets only in `.env` (gitignored). Never log or commit tokens. Paid providers are disabled by default and
   gated by `budget.max_cost_usd` (default 0) through the cost ledger.
7. No watermark removal. Voices are never mixed inside one video (fallback switches the whole project).
8. `providers.llm` in config is the machine allow-list; a workflow's `llm_chain` only orders it.
   A file `work/llm/<task>.response.json` always wins over any CLI (manual paste path).
9. Don't claim tests pass unless you ran them; report real output.

## Conventions
- Workflows are data: add `workflows/<name>/workflow.yaml` + stage functions registered in
  `studio.workflows.get_stages()`. Generator stages (source/script/scenes/storyboard) keep existing output unless
  `--force`; user edits to `project.json` survive re-runs.
- Timing: `audio_driven` (scene = voice + pad, frame aligned) or `fixed` (voice overflow > 200 ms fails).
- Formats in `config/formats.yaml` (`short_9x16`, `long_16x9`, `square_1x1`, `test_9x16`, `test_16x9`).
- Tests use `test_*` formats, `mock-vi` voice and an offline LLM chain (`tests/conftest.py`).
- Docs for the user are in Vietnamese (`README.md`, `docs/`).

## Roadmap
M0–M3.5 done on laptop (core, voices, story_reader, ai_cinematic, knowledge_explainer + Manim, worker + remote run; the worker is not yet
installed on the GPU PC). Next: GPU job types on the worker (TTS GPU voices, ComfyUI) · M4 text_quote / listicle_stock / ai_slideshow (ComfyUI on GPU node) · M6 longform ·
M7 motion_3d. See `docs/ARCHITECTURE.md` and `docs/WORKFLOWS.md`.
