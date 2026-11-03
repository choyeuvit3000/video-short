# CLAUDE.md — video-short (AI Shorts Studio v2)

The user writes in Vietnamese: answer in Vietnamese, keep code/comments/identifiers in English.

## What this is
A Windows-first CLI (`studio`) that builds short (9:16) and long (16:9) videos through **workflow recipes**.
Existing tools do the work (FFmpeg, Pillow, edge-tts/Piper, faster-whisper); AI CLIs (`claude -p`, `agy -p`,
`codex exec`) only write scripts/storyboards; web-only AI steps (ChatGPT images, Google Flow clips) are
**manual gates**. Two machines: this laptop = controller; a home PC with RTX 3080 10 GB = GPU node
(worker service is milestone M3.5, not built yet).

If you are running on the **GPU PC**, your task is probably `docs/SETUP_GPU_NODE.md` — follow it step by step.

## Commands
```powershell
uv venv --python 3.11 .venv ; uv pip install -e ".[piper,align,dev]"     # laptop  (GPU PC: ".[gpu,dev]")
.\.venv\Scripts\python.exe -m pytest -q          # needs ffmpeg on PATH or $env:STUDIO_FFMPEG_DIR, else ffmpeg tests skip
.\.venv\Scripts\ruff.exe check .                 # line-length 120
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_windows.ps1    # 3 real renders, --strict
studio doctor [--gpu]
```
Set `$env:PYTHONIOENCODING="utf-8"` when piping output that contains Vietnamese.

## Layout
- `src/studio/core/` — schema (project.json v2 + v1 upgrade), config (studio.yaml + local.yaml + .env), paths
  (`resolve_inside` refuses traversal/absolute), ffmpeg (arg lists only), media_probe, subtitles (SRT/ASS,
  word highlight), validator, qc, cost ledger, cache, logging, errors (exit codes).
- `src/studio/pipeline/` — `runner.py` (stages, state.json, manual gate → TODO_MANUAL.md + exit 3), `voice.py`
  (TTS + alignment + timeline.json).
- `src/studio/renderers/render.py` — per-scene segments → concat → audio mix/ducking → captions → atomic final.
- `src/studio/providers/` — `llm/` (claude/agy/codex CLIs + manual), `tts/` (edge, piper, mock, paid adapters
  disabled), `align.py` (provider words → faster-whisper → estimate), `source/` (text file, URL, Reddit OAuth,
  Threads API). `renderers/card.py` draws the post card; `voices.py` loads the voice registry.
- `src/studio/workflows/` — stage functions per workflow (`story_reader.py`, `ai_cinematic.py`, `common.py`);
  recipes live in `workflows/<name>/workflow.yaml` (stages, defaults, format_overrides, llm_chain) + prompts.
- `voices/` — registry + profile YAMLs; models in `voices/local/models/` (gitignored, per machine).
- `config/nodes.yaml` — worker nodes (tokens only via `token_env` → `.env`).

## Invariants (do not break)
1. Never overwrite, move or delete user input media (`clips/`, `images/`, `source/`, `audio/` given by user).
   Generated files go to `work/` and `output/` only; final video is written to a temp file then renamed.
2. Every subprocess call uses an argument list — never `shell=True`. Paths with spaces + Vietnamese must work.
3. Errors carry `code` and `scene_id` when scene-specific; exit codes: 0 ok, 1 error, 2 validation,
   3 waiting_manual, 4 budget, 5 QC fail. Never report success without a probed, valid output file.
4. No browser automation, scraping, cookie/session capture or quota bypass of Claude/ChatGPT/Flow/etc.
   Content comes from official APIs or text the user pastes.
5. Secrets only in `.env` (gitignored). Never log or commit tokens. Paid providers are disabled by default and
   gated by `budget.max_cost_usd` (default 0) through the cost ledger.
6. No watermark removal. Voices are never mixed inside one video (fallback switches the whole project).
7. `providers.llm` in config is the machine allow-list; a workflow's `llm_chain` only orders it.
   A file `work/llm/<task>.response.json` always wins over any CLI (manual paste path).
8. Don't claim tests pass unless you ran them; report real output.

## Conventions
- Workflows are data: add `workflows/<name>/workflow.yaml` + stage functions registered in
  `studio.workflows.get_stages()`. Generator stages (source/script/scenes/storyboard) keep existing output unless
  `--force`; user edits to `project.json` survive re-runs.
- Timing: `audio_driven` (scene = voice + pad, frame aligned) or `fixed` (voice overflow > 200 ms fails).
- Formats in `config/formats.yaml` (`short_9x16`, `long_16x9`, `square_1x1`, `test_9x16`, `test_16x9`).
- Tests use `test_*` formats, `mock-vi` voice and an offline LLM chain (`tests/conftest.py`).
- Docs for the user are in Vietnamese (`README.md`, `docs/`).

## Roadmap
M0–M3 done on laptop (core, voices, story_reader, ai_cinematic). Next: M3.5 worker (FastAPI + SQLite queue,
Tailscale, Task Scheduler) · M4 text_quote / listicle_stock / ai_slideshow (ComfyUI on GPU node) · M6 longform ·
M7 motion_3d. See `docs/ARCHITECTURE.md` and `docs/WORKFLOWS.md`.
