"""Chuẩn hóa chữ tiếng Việt để tìm kiếm có dấu và không dấu.

Chỉ dùng cho chỉ mục tìm kiếm. Nguyên văn văn bản không bao giờ bị sửa.
"""

from __future__ import annotations

import re
import unicodedata

_SPACE_RE = re.compile(r"\s+")


def nfc(text: str) -> str:
    """Đưa chuỗi về dạng Unicode NFC (dạng dựng sẵn), giữ nguyên chữ."""
    return unicodedata.normalize("NFC", text)


def bo_dau(text: str) -> str:
    """Bỏ dấu tiếng Việt và chuyển về chữ thường: 'Điều 5' -> 'dieu 5'."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    return _SPACE_RE.sub(" ", text).strip().lower()


def chuan_hoa_so_ky_hieu(so: str) -> str:
    """Chuẩn hóa số ký hiệu để so khớp: bỏ khoảng trắng, chữ hoa, bỏ dấu.

    '59/2020/qh14 ' -> '59/2020/QH14'; 'Số: 45/2019/QH14' -> '45/2019/QH14'.
    """
    so = nfc(so).strip()
    so = re.sub(r"^(s[oố]\s*[:.]?\s*)", "", so, flags=re.IGNORECASE)
    so = so.replace("Đ", "D").replace("đ", "d")
    so = re.sub(r"\s+", "", so)
    return bo_dau(so).upper()


def chuan_hoa_ten_co_quan(ten: str) -> str:
    return bo_dau(ten or "")
