# M · knowledge_explainer

Video kiến thức (khoa học, lịch sử, tài chính, toán, công nghệ, địa lý, tâm lý, sức khỏe). Mỗi cảnh là một
animation Manim (biểu đồ, dòng thời gian, công thức, quy trình...) chạy theo lời đọc. Chi phí ~0.

```powershell
uv pip install -e ".[manim]"                       # một lần
studio topics                                      # xem các chủ đề
studio new knowledge_explainer "lai-kep" --topic finance --brief "Lãi kép là gì, vì sao nên bắt đầu sớm"
studio run "projects\knowledge_explainer\<dir>"    # AI viết kịch bản -> dừng ở bước duyệt (exit 3)
# đọc TODO_MANUAL.md, kiểm tra số liệu + nguồn, sửa project.json nếu cần
studio approve "projects\knowledge_explainer\<dir>"
studio run "projects\knowledge_explainer\<dir>"    # đọc giọng, render Manim, QC, xuất video
```

- AI chỉ chọn template và điền tham số JSON; không có code do AI viết được chạy.
- Chủ đề tài chính và sức khỏe tự thêm câu miễn trừ trách nhiệm vào mô tả và lên màn hình.
- Chi tiết template, cảnh Manim tự viết, bản quyền: `docs/MANIM.md`.
