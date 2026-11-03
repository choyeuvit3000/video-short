# Cài đặt trên laptop (máy điều khiển)

Áp dụng cho Windows 10/11, không cần GPU NVIDIA. Mọi lệnh chạy trong **PowerShell**, tại thư mục repo.

## 1. Công cụ hệ thống

```powershell
winget install Git.Git GitHub.cli astral-sh.uv Gyan.FFmpeg
```

Đóng rồi mở lại terminal để PATH cập nhật, sau đó kiểm tra:

```powershell
git --version; gh --version; uv --version; ffmpeg -version
```

Nếu `ffmpeg` vẫn chưa nhận, ghi đường dẫn thư mục `bin` của FFmpeg vào `.env`:
`STUDIO_FFMPEG_DIR=C:\Users\<bạn>\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_...\ffmpeg-...-full_build\bin`.
Bản Gyan *full build* đã có `libass` (cần để in caption lên video) và filter `gradients`.

## 2. Lấy mã nguồn

```powershell
gh auth login                          # chọn GitHub.com → HTTPS → đăng nhập bằng trình duyệt
gh repo clone kaitosherlock/video-short F:\Project\video-short
cd F:\Project\video-short
```

## 3. Môi trường Python

```powershell
uv venv --python 3.11 .venv
uv pip install -e ".[piper,align,dev]"
.\.venv\Scripts\Activate.ps1           # nếu bị chặn: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

| Extra | Nội dung |
|---|---|
| `piper` | giọng đọc offline Piper (CPU) |
| `align` | faster-whisper, dùng để lấy mốc thời gian từng từ khi giọng không tự cung cấp |
| `dev` | pytest, ruff |

## 4. Cấu hình

```powershell
Copy-Item .env.example .env            # mọi key đều không bắt buộc; điền khi cần Reddit/Threads/Pexels
```

- Không bao giờ commit `.env`; file này đã có trong `.gitignore`.
- Cấu hình riêng cho máy này đặt trong `config/local.yaml` (gitignored), ghi đè lên `config/studio.yaml`. Ví dụ:

```yaml
providers:
  llm: [claude_cli, agy_cli, manual]   # danh sách CLI AI được phép dùng trên máy này
```

## 5. Kiểm tra

```powershell
studio doctor
studio voices install piper-vi-vais1000   # giọng Việt offline, dùng khi edge-tts lỗi hoặc mất mạng
studio voices install piper-en-lessac     # (tùy chọn) giọng Anh offline
studio voices test edge-vi-hoaimy
```

`doctor` cần **OK** ở các mục: python, ffmpeg, ffprobe, libass, font, edge_tts và quyền ghi. Các CLI AI (claude/agy/codex) không bắt buộc. Thiếu CLI nào thì chuỗi LLM bỏ qua CLI đó, và nếu không còn CLI nào thì chuyển sang bước thủ công.

## 6. Chạy test và smoke

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest -q
ruff check .
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_windows.ps1 -Voice edge-vi-hoaimy -Keep   # thử giọng thật
```

Smoke test render 3 project trong thư mục có tên tiếng Việt và dấu cách (`%TEMP%\studio smoke\thử nghiệm ...`), với `--strict`. Kết quả cuối phải là `SMOKE PASSED`.

## 7. Thêm tài nguyên (tùy chọn)

- **Nền** cho story_reader: video hoặc ảnh bạn có quyền dùng, đặt vào `assets/workflows/story_reader/backgrounds/`.
- **Nhạc nền**: `assets/shared/music/`, rồi đặt `audio.background_music` trong `project.json`.
- **Font**: `assets/shared/fonts/`. Nếu để trống, studio dùng Arial Bold của Windows.
- Ghi nguồn và license của từng file vào `assets/library.json`.

## 8. AI CLI

| CLI | Cài | Dùng để |
|---|---|---|
| `claude` | Claude Code | viết lại, dịch kịch bản, storyboard (ưu tiên số 1) |
| `agy` | Antigravity CLI | dự phòng, research ngữ cảnh dài |
| `codex` | `npm i -g @openai/codex` | dự phòng; dev và sửa code |

Các CLI này được gọi ở chế độ headless (`-p` / `exec`) và dùng quota gói thuê bao của bạn. Tool không lưu cookie hay token của chúng.
