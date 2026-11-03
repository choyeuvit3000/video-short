# Cài đặt PC RTX 3080 (GPU node) — checklist cho Claude Code

> **Cách dùng:** trên PC, mở Claude Code trong thư mục repo và nói:
> *"Làm theo docs/SETUP_GPU_NODE.md, từng bước, kiểm tra xong mới sang bước sau, cuối cùng báo cáo bảng kết quả."*
>
> Nếu PC chưa có repo, mở Claude Code ở thư mục bất kỳ (ví dụ `D:\`) và nói:
> *"Cài git, gh, uv rồi clone repo private choyeuvit3000/video-short vào D:\video-short, sau đó làm theo docs/SETUP_GPU_NODE.md."*

**Ghi chú cho Claude:**

- Chạy lệnh trong PowerShell.
- Bước nào cần người dùng thao tác thì **dừng lại và hỏi**: đăng nhập `gh` / Tailscale, cấu hình router, tải model cần chấp nhận license.
- Không tự đổi cài đặt bảo mật hệ thống.
- Không lưu token vào repo; token chỉ nằm trong `.env`.
- Báo kết quả thật của từng lệnh kiểm tra.

Vai trò của máy này: chạy các việc nặng (encode NVENC, faster-whisper CUDA, ComfyUI ảnh/video, TTS GPU) trong khung giờ rảnh.

Phần **worker service** (nhận job từ laptop qua mạng) thuộc milestone **M3.5, chưa được viết**. Bây giờ chỉ chuẩn bị máy và chạy studio local trên PC. Bước 9 là phần dành cho sau này.

---

## Bước 0 — Thông tin máy

- [ ] `nvidia-smi` → ghi lại tên GPU, driver và CUDA version. Cần driver ≥ 550; nếu thấp hơn, báo người dùng cập nhật qua GeForce Experience hoặc NVIDIA App.
- [ ] `Get-PSDrive -PSProvider FileSystem` → chọn ổ còn ≥ 100 GB trống cho model. Gọi thư mục đó là `$NODE`, ví dụ `D:\studio-node`.
- [ ] `winget --version` có chạy.

## Bước 1 — Công cụ hệ thống

```powershell
winget install Git.Git GitHub.cli astral-sh.uv Gyan.FFmpeg 7zip.7zip
```

- [ ] Mở terminal mới, kiểm tra `git`, `gh`, `uv`, `ffmpeg -version`.
- [ ] `ffmpeg -hide_banner -encoders | Select-String nvenc` → phải có `h264_nvenc`.

## Bước 2 — Lấy repo

```powershell
gh auth login                                   # NGƯỜI DÙNG đăng nhập: GitHub.com → HTTPS → browser
gh repo clone choyeuvit3000/video-short D:\video-short
cd D:\video-short
```

- [ ] `git log --oneline -3` hiện các commit.

## Bước 3 — Python và studio

```powershell
uv venv --python 3.11 .venv
uv pip install -e ".[gpu,dev]"
Copy-Item .env.example .env
```

- [ ] `.\.venv\Scripts\studio.exe doctor --gpu`: các mục python, ffmpeg, libass, font, `nvidia-smi` và `h264_nvenc encode` phải **OK**.
- [ ] Tạo `config/local.yaml` (gitignored) cho riêng máy này:

```yaml
render:
  encoder: h264_nvenc          # encode final bằng GPU
align:
  faster_whisper_model: large-v3
  device: cuda
  compute_type: float16
providers:
  llm: [claude_cli, manual]    # chỉ liệt kê CLI AI thật sự cài trên PC
```

## Bước 4 — faster-whisper chạy CUDA

faster-whisper (CTranslate2) trên Windows cần thêm **cuBLAS + cuDNN 9 cho CUDA 12**.

- [ ] Tải bộ thư viện NVIDIA cho Windows theo hướng dẫn trong README của faster-whisper (mục *GPU*: gói thư viện từ dự án `Purfview/whisper-standalone-win`). Giải nén vào `$NODE\cuda-libs`, rồi thêm thư mục đó vào PATH của user. **Hỏi người dùng trước khi sửa PATH.**
- [ ] Kiểm tra:

```powershell
.\.venv\Scripts\python.exe -c "import ctranslate2; print('cuda devices:', ctranslate2.get_cuda_device_count())"
```

  Kết quả phải ≥ 1. Thử thêm một lần align thật: `studio voices test edge-vi-hoaimy`, rồi chạy một project và xem log có dòng `loading faster-whisper large-v3 on cuda/float16`.
- Nếu không làm được thì để `device: cpu` và báo lại. Đây không phải lỗi chặn vì edge-tts đã tự trả mốc thời gian từng từ.

## Bước 5 — Smoke test trên PC

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_windows.ps1 -Keep
```

- [ ] pytest: tất cả pass, ghi lại số test.
- [ ] Smoke: `SMOKE PASSED`. Trong log của project (`logs\run_*.log`), dòng `[render] ...` phải ghi `encoder h264_nvenc`. Nếu có số liệu, so sánh thời gian render với laptop.

## Bước 6 — Giọng đọc

- [ ] `studio voices install piper-vi-vais1000` và `studio voices install piper-en-lessac`
- [ ] `studio voices test piper-vi-vais1000`
- Các giọng GPU (`f5tts-vi`, `vieneu-vi`, `xtts-v2-clone`) đang ở trạng thái `planned` trong `voices/local/manifest.yaml`, **chưa cài**. Chúng sẽ được tích hợp cùng worker (M3.5). Mỗi giọng sẽ có venv riêng trong `$NODE\tts\<tên>` để không xung đột torch với studio.

## Bước 7 — ComfyUI (ảnh và video local)

Dùng bản **ComfyUI Windows portable** chính thức (có sẵn Python và torch CUDA):

- [ ] Tải bản portable mới nhất cho NVIDIA từ trang Releases của `comfyanonymous/ComfyUI` (GitHub), giải nén bằng 7-Zip vào `$NODE\ComfyUI_windows_portable`. **Báo người dùng tên file và dung lượng trước khi tải.**
- [ ] Chạy `run_nvidia_gpu.bat`. ComfyUI chỉ lắng nghe ở `127.0.0.1:8188`. **Không** thêm `--listen` và không mở port này ra ngoài: sau này worker sẽ gọi ComfyUI từ chính máy này.
- [ ] Model gợi ý cho 10 GB VRAM. Người dùng chọn, tải từ trang chính thức và chấp nhận license nếu có:
  - Ảnh: SDXL base 1.0 (~7 GB) hoặc FLUX.1-schnell bản fp8/GGUF Q4–Q5 (vừa 10 GB, license Apache-2.0).
  - Video (thử nghiệm, chậm): LTX-Video hoặc Wan 2.x bản nhỏ (1.3B / GGUF).
  - Đặt đúng thư mục `ComfyUI\models\checkpoints|unet|vae|clip`.
- [ ] Render thử một ảnh 1024×1024 từ workflow mặc định và ghi lại thời gian cùng VRAM đỉnh (xem `nvidia-smi`).
- [ ] Lưu workflow API JSON dùng được vào `config/comfyui_workflows/` (ví dụ `sdxl_keyframe.json`), rồi commit lên một nhánh mới.

## Bước 8 — Mạng an toàn (Tailscale)

Người dùng **đã mở port trên router**. Đây là rủi ro: dịch vụ chạy job không bao giờ nên lộ ra internet.

- [ ] `winget install Tailscale.Tailscale`, sau đó **người dùng** đăng nhập cùng tài khoản trên cả PC và laptop.
- [ ] `tailscale ip -4` → ghi IP `100.x.y.z`. Đặt tên máy là `home-gpu` trong trang quản trị Tailscale.
- [ ] Từ laptop: `ping home-gpu` hoặc `tailscale ping home-gpu` thông.
- [ ] **Người dùng** vào trang quản trị router, **xóa rule port forwarding** đã mở. Kiểm tra lại bằng một dịch vụ kiểm tra port từ bên ngoài.
- [ ] Remote Desktop, nếu cần, chỉ dùng qua IP Tailscale.

## Bước 9 — (sau M3.5) Worker theo khung giờ

Phần này chỉ làm khi `src/studio/worker/` đã tồn tại.

- `.env`: `STUDIO_NODE_HOME_GPU_TOKEN=<chuỗi ngẫu nhiên dài>`, cùng giá trị trên laptop. Tạo chuỗi bằng:
  `[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))`
- Worker chỉ bind vào IP Tailscale, chỉ nhận các loại job định nghĩa sẵn, không có endpoint shell.
- `scripts/install_worker.ps1` sẽ tạo task trong Task Scheduler, chạy theo `schedule` trong `config/nodes.yaml` (mặc định `mon-fri 08:30-17:30`) và tự nhường GPU khi người dùng đang dùng máy.
- Power Options: không cho máy sleep trong khung giờ worker.
- Trên laptop: `config/nodes.yaml` đặt `home-gpu.enabled: true` và `url: http://home-gpu:8765`.

## Báo cáo cuối (Claude điền)

| Hạng mục | Kết quả |
|---|---|
| GPU / driver / CUDA | |
| doctor --gpu | |
| pytest | |
| smoke (encoder) | |
| faster-whisper CUDA | |
| Piper voices | |
| ComfyUI + model + thời gian 1 ảnh | |
| Tailscale IP / port router đã đóng | |
| Việc còn lại cho người dùng | |

Quy tắc git trên PC: `git pull` trước khi làm, tạo nhánh mới (`git switch -c pc/<việc>`), không commit `.env` / `config/local.yaml` / model.
