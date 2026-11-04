<#
.SYNOPSIS
Install the isolated official OmniVoice runtime. Existing VieNeu environment is untouched.
Models download on first audition. Reference audio and human QC are required before production.
Official upstream: https://github.com/k2-fsa/OmniVoice
#>
param([string]$Root = "D:\studio-node\tts\omnivoice")
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is required" }
$omniPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $omniPython)) {
    uv venv --python 3.12 (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Creating OmniVoice environment failed" }
}
uv pip install --python $omniPython torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed" }
uv pip install --python $omniPython omnivoice==0.2.1 transformers==5.22.1
if ($LASTEXITCODE -ne 0) { throw "OmniVoice installation failed" }
& $omniPython -c "import torch, omnivoice; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) { throw "OmniVoice CUDA check failed" }
Write-Host "OmniVoice installed: $omniPython"
