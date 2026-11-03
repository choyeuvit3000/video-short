<#
.SYNOPSIS
  Register studio-worker in Windows Task Scheduler (run on the worker PC, from the repo).

.DESCRIPTION
  The task starts `pythonw -m studio worker serve` (no console window) and restarts it if it stops.
  The worker stays running all the time but only takes jobs inside the node's `schedule` in
  config/nodes.yaml, and waits while you use the PC (policy.yield_if_user_active) or the GPU is busy.

  Prerequisites (docs/SETUP_GPU_NODE.md, Bước 9):
    - config/local.yaml:  worker: {node_id: home-gpu, host: <Tailscale IP 100.x.y.z>}
    - .env:               STUDIO_NODE_HOME_GPU_TOKEN=<same long random value as on the laptop>

  Default trigger: at logon of the current user (needed for "user active" detection).
  -AtStartup: at boot even without logon (run as Administrator; idle detection then cannot see you).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\install_worker.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\install_worker.ps1 -Uninstall
#>
param(
    [switch]$Uninstall,
    [switch]$AtStartup,
    [string]$TaskName = "studio-worker"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed task '$TaskName'."
    } else {
        Write-Host "Task '$TaskName' is not installed."
    }
    exit 0
}

$python = Join-Path $root ".venv\Scripts\python.exe"
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "No .venv in $root - run: uv venv --python 3.11 .venv; uv pip install -e "".[gpu,dev]""" }

# Validate config + token exactly as the worker will (prints node id and data folder)
Push-Location $root
try {
    $check = & $python -c "from studio.core.config import get_settings; from studio.worker.service import WorkerService; w = WorkerService(get_settings()); print(w.node_id); print(w.data_dir); print(w.settings.get('worker.host')); print(w.settings.get('worker.port'))" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "worker config check failed:`n$($check -join "`n")" }
} finally { Pop-Location }
$nodeId, $dataDir, $bindHost, $port = @($check)[-4..-1]
if ($bindHost -in @("127.0.0.1", "localhost")) {
    Write-Warning "worker.host is $bindHost - the laptop cannot reach it. Set worker.host to this PC's Tailscale IP (tailscale ip -4) in config/local.yaml."
}
if ($nodeId -eq "worker") {
    Write-Warning "worker.node_id is not set in config/local.yaml - schedule/policy from config/nodes.yaml will not apply."
}
$logFile = Join-Path $dataDir "worker.log"

$action = New-ScheduledTaskAction -Execute $pythonw -WorkingDirectory $root `
    -Argument "-m studio worker serve --log-file `"$logFile`""
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$user = "$env:USERDOMAIN\$env:USERNAME"
if ($AtStartup) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "AI Shorts Studio worker node '$nodeId' (http://${bindHost}:$port). Log: $logFile" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 4
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Task '$TaskName' installed and started (last result: $($info.LastTaskResult))."
Write-Host "  node:  $nodeId   listen: http://${bindHost}:$port"
Write-Host "  log:   $logFile"
Write-Host "Check from the laptop:  studio nodes status"
