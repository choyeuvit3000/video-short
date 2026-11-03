<#
.SYNOPSIS
  End-to-end smoke test on Windows: renders 3 real projects in a folder whose path has spaces and
  Vietnamese characters, each through `studio run --strict` (QC warnings fail).

    a) ai_cinematic  short_9x16  3 fixed 8 s clips (storyboard from a fixture response, no LLM)
    b) story_reader  short_9x16  post card + gradient, audio-driven timing
    c) story_reader  long_16x9   same source, landscape

  Default voice is mock-vi (offline, deterministic). Use -Voice edge-vi-hoaimy to include the
  real free TTS, or piper-vi-vais1000 after `studio voices install piper-vi-vais1000`.

.EXAMPLE
  .\scripts\smoke_test_windows.ps1
  .\scripts\smoke_test_windows.ps1 -Voice edge-vi-hoaimy -Keep
#>
param(
    [string]$Voice = "mock-vi",
    [string]$WorkRoot = (Join-Path $env:TEMP "studio smoke"),
    [switch]$Keep
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$studio = Join-Path $root ".venv\Scripts\studio.exe"
if (-not (Test-Path $studio)) { $studio = "studio" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$work = Join-Path $WorkRoot ("thử nghiệm " + $stamp)
$fixtures = Join-Path $work "fixtures"
& (Join-Path $PSScriptRoot "create_test_fixtures.ps1") -Out $fixtures

$results = @()

function Invoke-Studio([string[]]$StudioArgs) {
    & $studio @StudioArgs | Out-Host
    return $LASTEXITCODE
}

function Test-Project([string]$Label, [string]$Dir) {
    $code = Invoke-Studio @("run", $Dir, "--strict")
    $final = Join-Path $Dir "output\final.mp4"
    $ok = ($code -eq 0) -and (Test-Path $final) -and ((Get-Item $final).Length -gt 0)
    $script:results += [pscustomobject]@{ Project = $Label; Exit = $code; Ok = $ok; Output = $final }
}

# a) ai_cinematic: clips + fixture storyboard
$a = Join-Path $work "a clips 9x16"
$code = Invoke-Studio @("new", "ai_cinematic", "smoke clips", "--brief-file", (Join-Path $fixtures "brief.md"),
                        "--set", "scene_count=3", "--voice", $Voice, "--dir", $a)
if ($code -ne 0) { throw "studio new (a) failed with exit $code" }
New-Item -ItemType Directory -Force -Path (Join-Path $a "work\llm"), (Join-Path $a "clips") | Out-Null
Copy-Item (Join-Path $fixtures "storyboard.response.json") (Join-Path $a "work\llm\storyboard.response.json")
Copy-Item (Join-Path $fixtures "scene_0*.mp4") (Join-Path $a "clips")
Test-Project "a ai_cinematic 9:16" $a

# b + c) story_reader short and long from the same post
foreach ($fmt in @("short_9x16", "long_16x9")) {
    $dir = Join-Path $work ("story " + $fmt)
    $code = Invoke-Studio @("new", "story_reader", "smoke story", "--text-file", (Join-Path $fixtures "post.md"),
                            "--set", "rewrite=none", "--format", $fmt, "--voice", $Voice, "--dir", $dir)
    if ($code -ne 0) { throw "studio new ($fmt) failed with exit $code" }
    Test-Project ("story_reader " + $fmt) $dir
}

$results | Format-Table -AutoSize
$failed = @($results | Where-Object { -not $_.Ok })
if ($failed.Count -gt 0) {
    Write-Host "SMOKE FAILED ($($failed.Count) project(s)) - logs in each project's logs\ folder: $work" -ForegroundColor Red
    exit 1
}
Write-Host "SMOKE PASSED - $($results.Count) projects rendered" -ForegroundColor Green
if ($Keep) { Write-Host "kept: $work" } else { Remove-Item -Recurse -Force $work }
exit 0
