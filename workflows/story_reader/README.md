# S1 · story_reader

Đọc lại bài viết nổi bật (Reddit / Threads / web) trên nền video lặp, card bài viết ở cảnh đầu,
caption từng từ. Chi phí ~0.

```powershell
# từ text dán tay (an toàn nhất, không cần API)
studio new story_reader "chuyen-reddit-1" --lang vi --text-file my_post.md --format short_9x16 --format long_16x9
# từ URL Reddit (cần REDDIT_CLIENT_ID/SECRET trong .env)
studio new story_reader "aita-123" --lang en --url https://www.reddit.com/r/AmItheAsshole/comments/abc123/...
studio run "projects\story_reader\<thu-muc-project>"
```

- File text: dòng đầu `# Tiêu đề`, sau đó (tùy chọn) các dòng `url:`, `author:`, `community:`, `score:`, rồi nội dung.
- Nền: bỏ video/ảnh bạn có quyền dùng vào `assets/workflows/story_reader/backgrounds/` (`background: auto` tự chọn), nếu không có thì dùng gradient.
- `options.rewrite`: `auto` (dùng AI CLI nếu có, không thì đọc nguyên văn) · `llm` (bắt buộc AI, dừng ở manual gate nếu không có CLI) · `none`.
- Nguồn khác ngôn ngữ project (EN→VI, VI→EN) tự bật AI để dịch.
- Sửa kịch bản: chỉnh `work/script.json` rồi `studio run <dir> --from scenes --force`.
- Credit nguồn nằm sẵn trong `output/metadata.md`.
