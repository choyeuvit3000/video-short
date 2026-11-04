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

Bước 0–8 chuẩn bị máy và chạy studio local trên PC. Bước 9 cài **worker service** (M3.5): laptop gửi project qua Tailscale, PC render trong khung giờ rảnh, laptop lấy kết quả về.

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
  Dòng `manim` cũng phải OK, vì extra `[gpu]` đã gồm manim. Thiếu manim thì worker không render được cảnh kiến thức (`knowledge_explainer`).
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
- [ ] **VieNeu-TTS v3 Turbo** (giọng GPU tự nhiên, 48 kHz, Apache-2.0, được dùng thương mại):
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\install_vieneu.ps1    # venv riêng D:\studio-node\tts\vieneu, ~3 GB
  ```
  Thêm vào `config/local.yaml`:
  ```yaml
  tts:
    vieneu: {python: D:\studio-node\tts\vieneu\.venv\Scripts\python.exe, hf_home: D:\studio-node\hf}
  voice_defaults: {vi: vieneu-vi-maianh}   # giọng mặc định tiếng Việt của máy này
  align: {faster_whisper_model: large-v3-turbo, device: cuda, compute_type: float16}
  ```
  Rồi chạy `studio voices test vieneu-vi-maianh`. Lần đầu mất vài phút vì phải tải model (~1 GB). Các giọng có sẵn: `vieneu-vi-maianh`, `-minhduc`, `-thuydung` (phong cách tin tức), `-ngochuyen`, `-thienminh`, `-myduyen` (tự nhiên / kể chuyện). Model không trả mốc thời gian từng từ, nên phụ đề được căn bằng faster-whisper trên GPU. Model nạp một lần mỗi lần `studio run` (~15–45 s), sau đó mỗi câu mất khoảng 1 giây. Audio có gắn watermark AI của VieNeu, đừng tắt.
- Các giọng `location: node:home-gpu` chỉ chạy trên PC này. Laptop gửi project bằng `studio run --node home-gpu`; nếu chạy trên laptop, cả project tự chuyển sang giọng dự phòng (edge).
- `f5tts-vi` và `xtts-v2-clone` vẫn ở trạng thái `planned`: các model F5-TTS tiếng Việt tốt nhất (`hynt/F5-TTS-Vietnamese-ViVoice`) dùng giấy phép CC-BY-NC-SA (cấm thương mại), XTTS-v2 cũng non-commercial.

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

## Bước 9 — Worker theo khung giờ (M3.5)

Worker là một dịch vụ HTTP nhỏ (`studio worker serve`): hàng đợi SQLite trên chính PC, chỉ nhận loại job `pipeline` (các stage `validate, voice, render, qc, package` của một project), không có endpoint chạy lệnh tùy ý. Laptop gửi file theo content hash (file PC đã có thì không gửi lại), PC chạy xong giữ kết quả, laptop lấy về bằng `studio jobs pull`.

**Làm sau Bước 8** (Tailscale đã chạy, port router đã đóng).

- [ ] Tạo token. Chạy **một lần**, giá trị này dùng chung cho PC và laptop:

```powershell
$b = New-Object byte[] 48; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)
```

  Ghi vào `.env` của PC: `STUDIO_NODE_HOME_GPU_TOKEN=<chuỗi vừa tạo>`. **Không** in token ra báo cáo; chỉ báo "đã tạo". Đưa token cho người dùng tự chép sang laptop qua kênh riêng (password manager), không gửi qua chat.

- [ ] Thêm vào `config/local.yaml` của PC (giữ nguyên các mục đã có ở Bước 3):

```yaml
worker:
  node_id: home-gpu            # lấy schedule/policy của home-gpu trong config/nodes.yaml
  host: 100.x.y.z              # IP Tailscale của PC (tailscale ip -4); KHÔNG dùng 0.0.0.0
  port: 8765
  data_dir: D:\studio-node\worker_data   # hàng đợi + file job; mặc định .\worker_data trong repo
```

  Muốn đổi khung giờ thì patch node trong cùng file: `nodes: [{id: home-gpu, schedule: {timezone: Asia/Ho_Chi_Minh, windows: ["mon-fri 08:30-17:30", "sat-sun 01:00-07:00"]}}]`.

- [ ] Smoke test worker trên chính PC (HTTP thật qua 127.0.0.1, không đụng config của repo):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_worker_local.ps1 -Encoder h264_nvenc
```

  Phải in `WORKER SMOKE PASSED`, và dòng `worker log pulled` phải có `encoder h264_nvenc`.

- [ ] Cài worker vào Task Scheduler (tự chạy khi đăng nhập, tự khởi động lại nếu dừng, không có cửa sổ console):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_worker.ps1
```

  Script kiểm tra config + token trước khi cài, cảnh báo nếu `worker.host` vẫn là `127.0.0.1`. Log nằm ở `<data_dir>\worker.log`. Gỡ: thêm `-Uninstall`. Tùy chọn `-AtStartup` (chạy quyền Administrator) cho phép chạy cả khi chưa đăng nhập, nhưng khi đó worker không biết người dùng có đang dùng máy hay không.

- [ ] Worker luôn chạy nhưng **chỉ nhận việc** khi: đang trong `schedule`, người dùng không chạm chuột/bàn phím trong `worker.idle_minutes` (10 phút), và GPU không bị process khác dùng quá `worker.busy_gpu_util` (40%). Job gửi ngoài giờ nằm chờ trong hàng đợi.
- [ ] Power Options: không cho máy sleep trong khung giờ worker (Settings → System → Power → Screen and sleep → *Never* khi cắm điện, hoặc ít nhất dài hơn khung giờ).
- [ ] **Người dùng** làm trên laptop:
  - `.env`: `STUDIO_NODE_HOME_GPU_TOKEN=<cùng chuỗi>`
  - `config/local.yaml`: `nodes: [{id: home-gpu, enabled: true, url: "http://100.x.y.z:8765"}]` (hoặc `http://home-gpu:8765` nếu MagicDNS của Tailscale bật)
  - `studio nodes status` → cột status của `home-gpu` là `online` (ngoài giờ: `online, outside schedule`), cột gpu hiện RTX 3080. Lỗi `node_auth` = token hai máy khác nhau; `node_offline` = chưa thông Tailscale hoặc worker chưa chạy.
  - Thử: `studio run <dir> --node home-gpu` (đợi và tự lấy kết quả) hoặc `--node home-gpu --no-wait` rồi sau đó `studio jobs pull <dir>`.

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
| worker smoke (encoder) | |
| Task Scheduler `studio-worker` + log | |
| laptop `studio nodes status` | |
| Việc còn lại cho người dùng | |

Quy tắc git trên PC: `git pull` trước khi làm, tạo nhánh mới (`git switch -c pc/<việc>`), không commit `.env` / `config/local.yaml` / model.
