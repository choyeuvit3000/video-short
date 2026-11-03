# L1 · ai_cinematic

Luồng gốc của spec: AI viết storyboard → bạn tạo ảnh (ChatGPT) và clip (Google Flow) bằng tay →
FFmpeg ghép. Thời lượng scene cố định (`timing_mode: fixed`); giọng dài hơn scene quá 200 ms là FAIL.

```powershell
studio new ai_cinematic "bi-an-kim-tu-thap" --lang vi
# viết ý tưởng vào source/brief.md
studio run "projects\ai_cinematic\<dir>"     # dừng (exit 3) với TODO_MANUAL.md chứa prompt từng scene
# lưu clips/scene_01.mp4 ... (hoặc tạm images/scene_01.png), rồi chạy lại:
studio run "projects\ai_cinematic\<dir>"
```

Không tự động hóa trình duyệt, không lấy cookie, không xóa watermark — xem `docs/WORKFLOW_MANUAL.md`.
