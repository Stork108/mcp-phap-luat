"""Tách văn bản pháp luật thành Phần/Chương/Mục/Điều/Khoản/Điểm/Phụ lục.

Nguyên tắc: không sửa một chữ nào của nguyên văn. Mỗi đơn vị giữ nguyên văn
của cả đơn vị (Điều gồm cả các Khoản bên trong), ghép từ đúng các dòng gốc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textnorm import nfc

# Thứ tự điểm theo cách đánh số văn bản Việt Nam (không có f, j, w, z).
DIEM_ORDER = list("abcdđeghiklmnopqrstuvxy")

LEVEL = {
    "phan": 1,
    "chuong": 2,
    "muc": 3,
    "tieu_muc": 4,
    "dieu": 5,
    "khoan": 6,
    "diem": 7,
}

TEN_LOAI = {
    "phan": "Phần",
    "chuong": "Chương",
    "muc": "Mục",
    "tieu_muc": "Tiểu mục",
    "dieu": "Điều",
    "khoan": "Khoản",
    "diem": "Điểm",
    "phu_luc": "Phụ lục",
    "mo_dau": "Phần mở đầu",
    "ket": "Phần kết",
}

RE_PHAN = re.compile(r"^(PHẦN|Phần)\s+(THỨ\s+|thứ\s+)?([A-ZÀ-Ỹa-zà-ỹ0-9IVXLCDM]+)\b\.?\s*(.*)$")
RE_CHUONG = re.compile(r"^(CHƯƠNG|Chương)\s+([IVXLCDM]+|\d+)\b\.?\s*(.*)$")
RE_MUC = re.compile(r"^(MỤC|Mục)\s+(\d+)\b\.?\s*(.*)$")
RE_TIEU_MUC = re.compile(r"^(TIỂU MỤC|Tiểu mục)\s+(\d+)\b\.?\s*(.*)$")
RE_DIEU = re.compile(r"^Điều\s+(\d+[a-zđ]?)\s*[.:]\s*(.*)$")
RE_KHOAN = re.compile(r"^(\d+[a-zđ]?)\.\s+\S")
RE_DIEM = re.compile(r"^([a-zđ])(\d?)\)\s+\S")
RE_PHU_LUC = re.compile(r"^(PHỤ LỤC|Phụ lục)\b\s*([IVXLCDM]+|\d+)?\s*[.:]?\s*(.*)$")
RE_KET = re.compile(r"^(Nơi nhận\s*:|.{0,40}(này|này đã) (được|đã được) Quốc hội .*thông qua)")


@dataclass
class Unit:
    loai: str
    so: str | None
    tieu_de: str | None
    lines: list[str] = field(default_factory=list)
    children: list["Unit"] = field(default_factory=list)
    parent: "Unit | None" = None

    @property
    def noi_dung(self) -> str:
        return "\n".join(self.lines).strip("\n")

    def nhan(self) -> str:
        ten = TEN_LOAI.get(self.loai, self.loai)
        return f"{ten} {self.so}" if self.so else ten

    def duong_dan(self) -> str:
        parts = []
        u: Unit | None = self
        while u is not None:
            parts.append(u.nhan())
            u = u.parent
        return " > ".join(reversed(parts))


@dataclass
class ParsedDocument:
    units: list[Unit]  # đơn vị cấp cao nhất, theo thứ tự
    header: dict

    def walk(self):
        """Duyệt mọi đơn vị theo thứ tự xuất hiện (tiền thứ tự)."""
        stack = list(reversed(self.units))
        while stack:
            u = stack.pop()
            yield u
            stack.extend(reversed(u.children))


def _khoan_hop_le(so: str, last: str | None) -> bool:
    """Chỉ nhận số khoản theo đúng thứ tự (1, 2, 3... hoặc 2a sau 2) để tránh nhận nhầm."""
    m = re.match(r"(\d+)([a-zđ]?)$", so)
    if not m:
        return False
    n, suffix = int(m.group(1)), m.group(2)
    if last is None:
        return n == 1 and not suffix
    lm = re.match(r"(\d+)([a-zđ]?)$", last)
    ln = int(lm.group(1))
    if suffix:
        return n == ln  # 2a ngay sau 2
    return n == ln + 1


def _diem_hop_le(chu: str, last: str | None) -> bool:
    if chu not in DIEM_ORDER:
        return False
    if last is None:
        return chu == "a"
    last_chu = last[0]
    if chu == last_chu:
        return True  # điểm a1), a2)... sau điểm a)
    return DIEM_ORDER.index(chu) == DIEM_ORDER.index(last_chu) + 1


def _is_title_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 200:
        return False
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.8


def parse_text(text: str) -> ParsedDocument:
    text = nfc(text).replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")

    roots: list[Unit] = []
    stack: list[Unit] = []
    mo_dau = Unit("mo_dau", None, None)
    started = False
    in_phu_luc = False
    pending_title: Unit | None = None  # Chương/Phần/Mục chờ dòng tiêu đề kế tiếp

    def open_unit(u: Unit, level: int) -> None:
        nonlocal stack
        while stack and LEVEL.get(stack[-1].loai, 0) >= level:
            stack.pop()
        if stack:
            u.parent = stack[-1]
            stack[-1].children.append(u)
        else:
            roots.append(u)
        stack.append(u)

    def open_top(u: Unit) -> None:
        nonlocal stack
        stack = []
        roots.append(u)
        stack.append(u)

    def nearest(loai: str) -> Unit | None:
        for u in reversed(stack):
            if u.loai == loai:
                return u
        return None

    for line in raw_lines:
        s = line.strip()
        opened: Unit | None = None

        if s:
            m_pl = RE_PHU_LUC.match(s)
            if m_pl and s.startswith("PHỤ LỤC") and started:
                opened = Unit("phu_luc", m_pl.group(2), m_pl.group(3) or None)
                open_top(opened)
                in_phu_luc = True
                started = True
                pending_title = None if opened.tieu_de else opened
            elif not in_phu_luc:
                m = None
                if started and RE_KET.match(s):
                    opened = Unit("ket", None, None)
                    open_top(opened)
                    pending_title = None
                elif (m := RE_PHAN.match(s)) and _is_title_line(s[:12]):
                    opened = Unit("phan", m.group(3), m.group(4) or None)
                elif (m := RE_CHUONG.match(s)):
                    opened = Unit("chuong", m.group(2), m.group(3) or None)
                elif (m := RE_MUC.match(s)) and started:
                    opened = Unit("muc", m.group(2), m.group(3) or None)
                elif (m := RE_TIEU_MUC.match(s)) and started:
                    opened = Unit("tieu_muc", m.group(2), m.group(3) or None)
                elif (m := RE_DIEU.match(s)):
                    opened = Unit("dieu", m.group(1), m.group(2) or None)
                else:
                    dieu = nearest("dieu")
                    if dieu is not None and stack and stack[-1].loai != "ket":
                        mk = RE_KHOAN.match(s)
                        md = RE_DIEM.match(s)
                        khoan_children = [c for c in dieu.children if c.loai == "khoan"]
                        last_khoan = khoan_children[-1].so if khoan_children else None
                        if mk and _khoan_hop_le(mk.group(1), last_khoan):
                            opened = Unit("khoan", mk.group(1), None)
                        elif md:
                            khoan = nearest("khoan")
                            parent = khoan if khoan is not None else dieu
                            diem_children = [c for c in parent.children if c.loai == "diem"]
                            last_diem = diem_children[-1].so if diem_children else None
                            so = md.group(1) + md.group(2)
                            if _diem_hop_le(md.group(1), last_diem):
                                opened = Unit("diem", so, None)
                if opened is not None and opened.loai in LEVEL:
                    open_unit(opened, LEVEL[opened.loai])
                    started = True
                    if opened.loai in ("phan", "chuong", "muc", "tieu_muc") and not opened.tieu_de:
                        pending_title = opened
                    else:
                        pending_title = None
                elif opened is None and pending_title is not None and _is_title_line(s):
                    pending_title.tieu_de = s
                    pending_title = None
                elif opened is None:
                    pending_title = None
            elif pending_title is not None and opened is None and _is_title_line(s):
                pending_title.tieu_de = s
                pending_title = None

        # Gắn dòng vào mọi đơn vị đang mở (nguyên văn), hoặc phần mở đầu.
        if not started:
            mo_dau.lines.append(line)
        else:
            for u in stack:
                u.lines.append(line)

    units = roots
    if any(x.strip() for x in mo_dau.lines):
        units = [mo_dau] + roots
    return ParsedDocument(units=units, header=extract_header(raw_lines))


# ---------------------------------------------------------------------------
# Đọc thông tin văn bản từ phần đầu (chỉ là gợi ý, phải đối chiếu nguồn)

LOAI_VAN_BAN = [
    "VĂN BẢN HỢP NHẤT",
    "THÔNG TƯ LIÊN TỊCH",
    "BỘ LUẬT",
    "LUẬT",
    "PHÁP LỆNH",
    "NGHỊ ĐỊNH",
    "NGHỊ QUYẾT LIÊN TỊCH",
    "NGHỊ QUYẾT",
    "THÔNG TƯ",
    "QUYẾT ĐỊNH",
    "CHỈ THỊ",
    "LỆNH",
]

CO_QUAN_PREFIX = (
    "QUỐC HỘI",
    "ỦY BAN THƯỜNG VỤ QUỐC HỘI",
    "UỶ BAN THƯỜNG VỤ QUỐC HỘI",
    "VĂN PHÒNG QUỐC HỘI",
    "CHÍNH PHỦ",
    "THỦ TƯỚNG CHÍNH PHỦ",
    "BỘ ",
    "NGÂN HÀNG NHÀ NƯỚC",
    "ỦY BAN NHÂN DÂN",
    "UỶ BAN NHÂN DÂN",
    "HỘI ĐỒNG NHÂN DÂN",
    "HỘI ĐỒNG THẨM PHÁN",
    "TÒA ÁN NHÂN DÂN TỐI CAO",
    "VIỆN KIỂM SÁT NHÂN DÂN TỐI CAO",
    "KIỂM TOÁN NHÀ NƯỚC",
)

RE_SO = re.compile(r"Số\s*[:.]?\s*(\d+[A-Za-zĐđ0-9./\-]*/[A-Za-zĐđ0-9./\-]+)")
RE_NGAY = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)
RE_HIEU_LUC = re.compile(
    r"có hiệu lực(?: thi hành)?(?: kể)? từ ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
    re.IGNORECASE,
)


def _iso(d: str, m: str, y: str) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def extract_header(lines: list[str]) -> dict:
    head = [l.strip() for l in lines[:60] if l.strip()]
    out: dict = {}
    for l in head:
        m = RE_SO.search(l)
        if m:
            out["so_ky_hieu"] = m.group(1).rstrip(".")
            break
    for l in head:
        m = RE_NGAY.search(l)
        if m:
            out["ngay_ban_hanh"] = _iso(*m.groups())
            break
    for l in head:
        if l.upper() == l and any(l.startswith(p) for p in CO_QUAN_PREFIX):
            out["co_quan_ban_hanh"] = l
            break
    for l in head:
        for loai in LOAI_VAN_BAN:
            if l == loai or l.startswith(loai + " "):
                out["loai_van_ban"] = loai.capitalize()
                break
        if "loai_van_ban" in out:
            break
    if "loai_van_ban" in out:
        # Trích yếu: các dòng ngay sau tên loại văn bản, trước 'Căn cứ'.
        idx = next(i for i, l in enumerate(head) if l.startswith(out["loai_van_ban"].upper()))
        parts = []
        for l in head[idx + 1 : idx + 4]:
            if l.startswith(("Căn cứ", "CĂN CỨ", "Theo đề nghị", "QUYẾT", "Số")) or _is_title_line(l) is False and parts:
                break
            parts.append(l)
        if parts:
            ty = " ".join(parts)
            ty = ty[0] + ty[1:].lower() if ty.isupper() else ty
            out["trich_yeu"] = (out["loai_van_ban"] + " " + ty) if out["loai_van_ban"] in ("Luật", "Bộ luật", "Pháp lệnh") else ty
    full = "\n".join(lines)
    m = RE_HIEU_LUC.search(full)
    if m:
        out["ngay_hieu_luc"] = _iso(*m.groups())
    if "ngay_ban_hanh" not in out:
        # Luật, nghị quyết của Quốc hội ghi ngày thông qua ở cuối văn bản.
        tail = "\n".join(lines[-40:])
        m = re.search(r"thông qua ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", tail)
        if m:
            out["ngay_ban_hanh"] = _iso(*m.groups())
    return out
