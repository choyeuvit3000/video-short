<#
.SYNOPSIS
  End-to-end worker smoke test on ONE machine, over real HTTP on 127.0.0.1.

.DESCRIPTION
  Starts `studio worker serve` in the background (its own STUDIO_HOME, data dir and random token), then a
  controller (another STUDIO_HOME) creates a story_reader project and:
    1. checks that a wrong token gets 401
    2. `studio run --node smoke-node --strict` (submit -> worker renders -> pull) must exit 0 with QC PASS
    3. `studio run --node smoke-node --no-wait` must exit 6, then `studio jobs pull` until exit 0
  Nothing is written to the repo's config/, cache/ or projects/.

  On the GPU PC:  -Encoder h264_nvenc  makes the worker encode with NVENC (check the pulled log).
#>
param(
    [string]$Voice = "mock-vi",
    [string]$Encoder = "libx264",
    [int]$Port = 8799,
    [string]$WorkRoot = (Join-Path $env:TEMP "studio worker smoke"),
    [switch]$Keep
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$studio = Join-Path $root ".venv\Scripts\studio.exe"
if (-not (Test-Path $studio)) { throw "studio.exe not found - install with: uv pip install -e "".[worker,dev]""" }

if (Test-Path $WorkRoot) { Remove-Item -Recurse -Force $WorkRoot }
$null = New-Item -ItemType Directory -Force $WorkRoot

function New-Home([string]$Name, [string]$LocalYaml) {
    $h = Join-Path $WorkRoot $Name
    foreach ($d in @("config", "workflows", "assets")) {
        Copy-Item -Recurse (Join-Path $root $d) (Join-Path $h $d)
    }
    $null = New-Item -ItemType Directory -Force (Join-Path $h "voices")
    Get-ChildItem (Join-Path $root "voices") | Where-Object { $_.Name -ne "local" } |
        ForEach-Object { Copy-Item -Recurse $_.FullName (Join-Path $h "voices") }
    $null = New-Item -ItemType Directory -Force (Join-Path $h "voices\local")
    Copy-Item (Join-Path $root "voices\local\manifest.yaml") (Join-Path $h "voices\local")
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $h "config\local.yaml")
    [IO.File]::WriteAllText((Join-Path $h "config\local.yaml"), $LocalYaml, (New-Object Text.UTF8Encoding $false))
    return $h
}

$bytes = New-Object byte[] 36
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$env:STUDIO_SMOKE_TOKEN = [Convert]::ToBase64String($bytes)
$nodeYaml = @"
nodes:
  - id: smoke-node
    role: worker
    enabled: true
    url: http://127.0.0.1:$Port
    token_env: STUDIO_SMOKE_TOKEN
"@
$workerHome = New-Home "worker home" @"
worker:
  node_id: smoke-node
  host: 127.0.0.1
  port: $Port
  poll_sec: 1
render:
  encoder: $Encoder
$nodeYaml
"@
$ctrlHome = New-Home "controller home" @"
providers:
  llm: [manual]
remote:
  poll_sec: 2
  wait_timeout_min: 15
$nodeYaml
"@

$env:PYTHONIOENCODING = "utf-8"
$env:STUDIO_HOME = $workerHome
$workerLog = Join-Path $WorkRoot "worker.log"
$worker = Start-Process -FilePath $studio -ArgumentList @("worker", "serve", "--ignore-schedule") -PassThru `
    -WindowStyle Hidden -RedirectStandardOutput $workerLog -RedirectStandardError (Join-Path $WorkRoot "worker.err.log")
$results = @()
try {
    $base = "http://127.0.0.1:$Port"
    $ok = $false
    for ($i = 0; $i -lt 60 -and -not $ok; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $h = Invoke-RestMethod "$base/v1/health" -Headers @{ Authorization = "Bearer $env:STUDIO_SMOKE_TOKEN" }
            $ok = $true
        } catch { if ($worker.HasExited) { break } }
    }
    if (-not $ok) { throw "worker did not start - see $workerLog and worker.err.log" }
    Write-Host "worker up: node=$($h.node_id) in_schedule=$($h.in_schedule)"

    try {
        Invoke-WebRequest "$base/v1/health" -Headers @{ Authorization = "Bearer wrong" } -UseBasicParsing | Out-Null
        $results += [pscustomobject]@{ Check = "wrong token -> 401"; Ok = $false }
    } catch {
        $results += [pscustomobject]@{ Check = "wrong token -> 401"; Ok = ($_.Exception.Response.StatusCode.value__ -eq 401) }
    }

    $env:STUDIO_HOME = $ctrlHome
    $fixtures = Join-Path $WorkRoot "fixtures"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "create_test_fixtures.ps1") -Out $fixtures | Out-Host
    & $studio nodes status | Out-Host

    $dir = Join-Path $WorkRoot "dự án gửi worker"
    & $studio new story_reader "worker smoke" --text-file (Join-Path $fixtures "post.md") --set rewrite=none `
        --format short_9x16 --voice $Voice --dir $dir | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "studio new failed ($LASTEXITCODE)" }

    & $studio run $dir --node smoke-node --strict | Out-Host
    $code = $LASTEXITCODE
    $qcFile = Join-Path $dir "output\qc_report.json"
    $qc = if (Test-Path $qcFile) { (Get-Content $qcFile -Raw -Encoding UTF8 | ConvertFrom-Json).status } else { "-" }
    $workerRunLog = Get-ChildItem (Join-Path $dir "logs") -Filter "*worker_*" -ErrorAction SilentlyContinue | Select-Object -First 1
    $encLine = if ($workerRunLog) { (Select-String -Path $workerRunLog.FullName -Pattern "encoder" | Select-Object -First 1).Line } else { "" }
    $results += [pscustomobject]@{ Check = "run --node (wait + pull): exit $code, QC $qc"; Ok = ($code -eq 0 -and $qc -eq "PASS" -and (Test-Path (Join-Path $dir "output\final.mp4"))) }
    $results += [pscustomobject]@{ Check = "worker log pulled: $encLine"; Ok = [bool]$workerRunLog }

    & $studio run $dir --node smoke-node --only render --only qc --no-wait | Out-Host
    $results += [pscustomobject]@{ Check = "run --no-wait -> exit 6"; Ok = ($LASTEXITCODE -eq 6) }
    $code = 6
    for ($i = 0; $i -lt 120 -and $code -eq 6; $i++) {
        Start-Sleep -Seconds 2
        & $studio jobs pull $dir | Out-Host
        $code = $LASTEXITCODE
    }
    $results += [pscustomobject]@{ Check = "jobs pull later -> exit $code"; Ok = ($code -eq 0) }
    & $studio jobs list --node smoke-node | Out-Host
}
finally {
    if ($worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id -Force }
    Remove-Item Env:STUDIO_HOME -ErrorAction SilentlyContinue
}

$results | Format-Table -AutoSize
if (@($results | Where-Object { -not $_.Ok }).Count -gt 0 -or $results.Count -lt 5) {
    Write-Host "WORKER SMOKE FAILED (logs: $WorkRoot)" -ForegroundColor Red
    exit 1
}
Write-Host "WORKER SMOKE PASSED" -ForegroundColor Green
if (-not $Keep) { Remove-Item -Recurse -Force $WorkRoot -ErrorAction SilentlyContinue }
exit 0
