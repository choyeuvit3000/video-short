<#
.SYNOPSIS
  Create offline test media: 3 colour clips with a tone, a sample post, a brief and a ready
  storyboard response (so the ai_cinematic workflow needs no LLM).

.EXAMPLE
  .\scripts\create_test_fixtures.ps1 -Out "$env:TEMP\studio fixtures"
#>
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Size = "540x960",
    [int]$Seconds = 8
)
$ErrorActionPreference = "Stop"

function Find-FFmpeg {
    if ($env:STUDIO_FFMPEG_DIR) {
        $p = Join-Path $env:STUDIO_FFMPEG_DIR "ffmpeg.exe"
        if (Test-Path $p) { return $p }
    }
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "ffmpeg not found: install it (winget install Gyan.FFmpeg) or set STUDIO_FFMPEG_DIR"
}

function Write-Utf8([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
}

$ffmpeg = Find-FFmpeg
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$clips = @(
    @{ Name = "scene_01.mp4"; Color = "red";   Freq = 440 },
    @{ Name = "scene_02.mp4"; Color = "green"; Freq = 550 },
    @{ Name = "scene_03.mp4"; Color = "blue";  Freq = 660 }
)
foreach ($c in $clips) {
    $target = Join-Path $Out $c.Name
    & $ffmpeg -v error -y `
        -f lavfi -i "color=c=$($c.Color):s=$($Size):r=30:d=$Seconds" `
        -f lavfi -i "sine=frequency=$($c.Freq):sample_rate=48000:duration=$Seconds" `
        -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $target
    if ($LASTEXITCODE -ne 0) { throw "ffmpeg failed creating $target" }
}

Write-Utf8 (Join-Path $Out "post.md") @"
# Tôi phát hiện bạn cùng phòng dùng trộm Netflix của tôi suốt hai năm
url: https://www.reddit.com/r/test/comments/abc123/x/
author: nguoi_dung_1
community: TroChuyen
score: 1234

Chuyện là thế này. Hai năm trước tôi chia sẻ mật khẩu cho bạn cùng phòng. Sau đó chúng tôi chuyển nhà.

Tuần trước tôi thấy một hồ sơ lạ tên "Gấu" trong tài khoản. Hóa ra là cậu ấy! Tôi nên làm gì bây giờ?
"@

Write-Utf8 (Join-Path $Out "brief.md") "Ba cảnh màu đỏ, xanh lá, xanh dương để kiểm tra pipeline."

Write-Utf8 (Join-Path $Out "storyboard.response.json") @"
{
  "title": "Kiểm tra ba cảnh",
  "description": "Video kiểm tra pipeline với ba clip màu.",
  "hashtags": ["kiemtra", "studio"],
  "style": "flat colour",
  "scenes": [
    {"duration_sec": 8, "narration": "Cảnh một: bầu trời màu đỏ.", "image_prompt": "red sky", "video_prompt": "static"},
    {"duration_sec": 8, "narration": "Cảnh hai: cánh đồng xanh.", "image_prompt": "green field", "video_prompt": "static"},
    {"duration_sec": 8, "narration": "Cảnh ba: biển xanh thẳm.", "image_prompt": "blue sea", "video_prompt": "static"}
  ]
}
"@

Write-Host "fixtures written to $Out"
