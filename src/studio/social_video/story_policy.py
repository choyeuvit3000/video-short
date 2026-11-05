"""Creator defaults for future horror stories; never squeeze speech to hit a timer."""

import re
from pathlib import Path


def closing_question(text):
    if re.search(r"trốn tìm|bụi tre|ma giấu", text, re.I):
        return "Ở quê bạn có chuyện ma giấu người như thế không?"
    if re.search(r"sông|xuồng|bến|ao|đìa", text, re.I):
        return "Ở quê bạn, chuyện bên bến nước thường được kể thế nào?"
    if re.search(r"giọng|tiếng ru|thì thào", text, re.I):
        return "Quê bạn có ai kể chuyện ma giả giọng như vậy chưa?"
    return "Ở quê bạn, người lớn thường giải thích chuyện này thế nào?"


def editorial_defaults(vi):
    paragraphs = vi.get("paragraphs", [])
    if not paragraphs or vi.get("closing_question") is False:
        return vi
    question = vi.get("closing_question") or closing_question(" ".join(paragraphs))
    if not " ".join(paragraphs).rstrip().endswith(question):
        paragraphs.append(question)
    vi["closing_question"] = question
    return vi


PROMPT = """
Ưu tiên kể đủ ý, đủ bối cảnh và các nút thắt; không ép nội dung vào ba mươi lăm giây.
Mục tiêu tham khảo là chín mươi giây; có thể dài hơn nếu mạch truyện cần.
Nếu chia phần, chọn điểm dừng ở tình huống gay cấn, không cắt ngang câu hay đọc số phần ở đầu.
Trả thêm suspense_breaks: chỉ số đoạn phù hợp để ngắt ở nút thắt; không đánh dấu bừa mọi đoạn.
Trả closing_question: một câu hỏi mở khoảng mười hai đến mười sáu từ, gắn tình huống
và cách kể dân gian địa phương. Không thêm sự kiện, không khẳng định điều siêu nhiên là thật,
không hứa hẹn tăng tương tác hoặc gán tên loại ma khi nguồn chưa xác định.
Nếu làm câu mở cho từng phần, chọn một sự kiện đứng riêng vẫn hiểu từ nguồn,
không mở bằng tóm tắt tập trước. Ưu tiên câu ngắn dưới mười lăm đơn vị ở cao trào,
dùng dấu chấm để tách nhịp, không chặt vụn mọi câu hay tự thêm khoảng nghỉ dài.
Chi tiết giác quan chỉ lấy từ nguồn đang dịch. Không bịa âm thanh, mùi, xúc giác,
nguyên nhân tai nạn hoặc quy tắc dân gian để đạt mục tiêu giữ chân.
"""


def original_story_prompt():
    """The original-fiction writing brief is separate from source-faithful translation."""
    rules = Path(__file__).resolve().parents[3] / "docs/EAST_ASIAN_HORROR_WRITING.md"
    return (
        "Sáng tác hư cấu theo yêu cầu người tạo; trình kịch bản để duyệt trước TTS.\n"
        + rules.read_text(encoding="utf-8")
    )
