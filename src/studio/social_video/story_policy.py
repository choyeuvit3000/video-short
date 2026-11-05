"""Creator defaults for future horror stories; never squeeze speech to hit a timer."""

import re


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
"""
