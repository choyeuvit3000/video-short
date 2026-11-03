<#
.SYNOPSIS
  Build the two demo videos (15-30 s, 1080x1920) and prove the acceptance checks with real runs.

    1) story_reader  Vietnamese voice + word captions, then the same `studio run` again: render, qc and
                     package are skipped because nothing changed.
    2) ai_cinematic  storyboard from a pasted AI answer (work/llm/storyboard.response.json), first run stops
                     at the manual gate (exit 3, TODO_MANUAL.md), sample clips stand in for the Google Flow
                     clips, second run resumes and finishes (exit 0).

  No paid API, no browser. -Voice edge-vi-hoaimy needs internet (free); piper-vi-vais1000 / mock-vi are
  offline. Results: <Out>\demo_summary.json (exit codes, QC, durations, skipped stages).

.EXAMPLE
  .\scripts\demo_videos.ps1
  .\scripts\demo_videos.ps1 -Voice piper-vi-vais1000
#>
param(
    [string]$Voice = "edge-vi-hoaimy",
    [string]$Out = (Join-Path (Split-Path -Parent $PSScriptRoot) "projects\_demo")
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$studio = Join-Path $root ".venv\Scripts\studio.exe"
if (-not (Test-Path $studio)) { $studio = "studio" }
$env:PYTHONIOENCODING = "utf-8"

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$work = Join-Path $Out $stamp
$fixtures = Join-Path $work "fixtures"
& (Join-Path $PSScriptRoot "create_test_fixtures.ps1") -Out $fixtures
$ffmpeg = if ($env:STUDIO_FFMPEG_DIR) { Join-Path $env:STUDIO_FFMPEG_DIR "ffmpeg.exe" } else { "ffmpeg" }

function Invoke-Studio([string[]]$StudioArgs) {
    & $studio @StudioArgs | Out-Host
    return $LASTEXITCODE
}

function Read-Json([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
}

function Get-Skipped([string]$Dir) {
    $st = Read-Json (Join-Path $Dir "state.json")
    return @($st.stages.PSObject.Properties | Where-Object { $_.Value.skipped } | ForEach-Object { $_.Name })
}

function Get-Result([string]$Dir) {
    $qc = Read-Json (Join-Path $Dir "output\qc_report.json")
    return [ordered]@{
        final = (Join-Path $Dir "output\final.mp4"); qc = $qc.status; warnings = @($qc.warnings)
        duration_sec = $qc.actual_duration_sec; video = $qc.video; lufs = $qc.checks.audio.integrated_lufs
        captions_outside_safe_zone = @($qc.checks.captions.outside_safe_zone).Count
        voice = (Read-Json (Join-Path $Dir "work\timeline.json")).voice_profile
    }
}

$summary = [ordered]@{ created = $stamp; voice_requested = $Voice }

# 1) story_reader
$s = Join-Path $work "1 story_reader 9x16"
$code = Invoke-Studio @("new", "story_reader", "demo truyện", "--text-file", (Join-Path $fixtures "post.md"),
                        "--set", "rewrite=none", "--format", "short_9x16", "--voice", $Voice, "--dir", $s)
if ($code -ne 0) { throw "studio new (story_reader) failed with exit $code" }
$first = Invoke-Studio @("run", $s, "--strict")
if ($first -ne 0) { throw "story_reader run failed with exit $first - see $s\logs" }
$mtime = (Get-Item (Join-Path $s "output\final.mp4")).LastWriteTimeUtc
$again = Invoke-Studio @("run", $s, "--strict")
$summary.story_reader = Get-Result $s
$summary.story_reader.first_run_exit = $first
$summary.story_reader.second_run_exit = $again
$summary.story_reader.second_run_skipped = Get-Skipped $s
$summary.story_reader.final_untouched_by_second_run = ((Get-Item (Join-Path $s "output\final.mp4")).LastWriteTimeUtc -eq $mtime)

# 2) ai_cinematic: manual gate, then resume with sample clips standing in for Flow
$c = Join-Path $work "2 ai_cinematic 9x16"
$code = Invoke-Studio @("new", "ai_cinematic", "demo điện ảnh", "--brief-file", (Join-Path $fixtures "brief.md"),
                        "--set", "scene_count=3", "--format", "short_9x16", "--voice", $Voice, "--dir", $c)
if ($code -ne 0) { throw "studio new (ai_cinematic) failed with exit $code" }
New-Item -ItemType Directory -Force -Path (Join-Path $c "work\llm") | Out-Null
Copy-Item (Join-Path $fixtures "storyboard.response.json") (Join-Path $c "work\llm\storyboard.response.json")
$gate = Invoke-Studio @("run", $c, "--strict")
$todo = Join-Path $c "TODO_MANUAL.md"
$summary.ai_cinematic = [ordered]@{ gate_run_exit = $gate; todo_written = (Test-Path $todo) }
if ($gate -ne 3) { throw "expected the manual gate (exit 3), got $gate" }

$sources = @("mandelbrot=s=540x960:r=30", "life=s=540x960:r=30:mold=10:ratio=0.12:life_color=#FFD24D:death_color=#3050C0",
             "gradients=s=540x960:r=30:speed=0.03")
$clips = Join-Path $c "clips"
New-Item -ItemType Directory -Force -Path $clips | Out-Null
for ($i = 0; $i -lt 3; $i++) {
    $target = Join-Path $clips ("scene_{0:d2}.mp4" -f ($i + 1))
    & $ffmpeg -v error -y -f lavfi -i $sources[$i] -t 8 -c:v libx264 -pix_fmt yuv420p $target
    if ($LASTEXITCODE -ne 0) { throw "ffmpeg failed creating $target" }
}
$clipTimes = @(Get-ChildItem $clips | ForEach-Object { $_.LastWriteTimeUtc })
$resume = Invoke-Studio @("run", $c, "--strict")
$summary.ai_cinematic.resume_run_exit = $resume
$summary.ai_cinematic.todo_removed = -not (Test-Path $todo)
$summary.ai_cinematic.input_clips_untouched = ((Compare-Object $clipTimes @(Get-ChildItem $clips | ForEach-Object { $_.LastWriteTimeUtc })) -eq $null)
if ($resume -eq 0) { foreach ($kv in (Get-Result $c).GetEnumerator()) { $summary.ai_cinematic[$kv.Key] = $kv.Value } }

$json = $summary | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText((Join-Path $work "demo_summary.json"), $json, (New-Object System.Text.UTF8Encoding $false))
Write-Host $json
$ok = ($first -eq 0) -and ($again -eq 0) -and ($resume -eq 0) -and ($gate -eq 3)
if ($ok) { Write-Host "DEMOS PASSED - $work" -ForegroundColor Green; exit 0 }
Write-Host "DEMOS FAILED - $work" -ForegroundColor Red
exit 1
