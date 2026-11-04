<#
.SYNOPSIS
  Install VieNeu-TTS v3 Turbo (GPU) in its own venv for the `vieneu` voice provider (run on the GPU PC).

.DESCRIPTION
  VieNeu pins torch 2.8 (CUDA 12.8) and transformers 4.57.6, so it gets a venv of its own instead of studio's.
  Model files (~1 GB) download on first use into -HfHome. Then add to config/local.yaml:

    tts:
      vieneu: {python: <Root>\.venv\Scripts\python.exe, hf_home: <HfHome>}
    voice_defaults: {vi: vieneu-vi-maianh}     # optional: make it this machine's default Vietnamese voice

  and check with:  studio voices test vieneu-vi-maianh

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\install_vieneu.ps1
#>
param(
    [string]$Root = "D:\studio-node\tts\vieneu",
    [string]$HfHome = "D:\studio-node\hf",
    [string]$VieneuVersion = "3.8.3"
)

$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv not found - winget install astral-sh.uv" }
New-Item -ItemType Directory -Force $Root, $HfHome | Out-Null
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { uv venv --python 3.12 (Join-Path $Root ".venv") }
uv pip install --python $py torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python $py "transformers==4.57.6" safetensors "vieneu==$VieneuVersion"
& $py -c "import torch; assert torch.cuda.is_available(), 'CUDA not available'; print('CUDA OK:', torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) { throw "torch cannot see the GPU - update the NVIDIA driver" }
Write-Host "VieNeu installed: $py"
Write-Host "HF cache (model downloads on first use): $HfHome"
