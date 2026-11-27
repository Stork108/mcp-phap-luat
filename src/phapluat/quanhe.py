"""Đọc quan hệ giữa văn bản (căn cứ, sửa đổi, thay thế, bãi bỏ, làm hết hiệu lực, hợp nhất)
từ chính nội dung văn bản đã có trong kho.

Dùng khi nguồn không cung cấp lược đồ quan hệ (vbpl.vn chỉ trả lược đồ qua /api/, robots.txt cấm).

Nguyên tắc thận trọng:
- Chỉ ghi quan hệ khi văn bản nêu rõ số ký hiệu của văn bản bị tác động.
- Bỏ qua chữ nằm trong ngoặc kép (là nội dung mới được đưa vào, không phải lệnh sửa đổi).
- Bỏ qua câu có "tiếp tục" (quy định chuyển tiếp).
- Mỗi quan hệ tự đọc đều mang nhãn TU_DOC trong ghi chú, kèm nguyên câu làm căn cứ,
  để người dùng đối chiếu. Chạy lại thì quan hệ tự đọc cũ của văn bản đó được xóa và đọc lại;
  quan hệ ghi tay không bị đụng tới.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .textnorm import bo_dau, chuan_hoa_so_ky_hieu

TU_DOC = "[tự đọc từ nội dung, cần đối chiếu]"

# Số ký hiệu: 31/2024/QH15, 123/2020/NĐ-CP, 01/2012/UBTVQH13, 18/VBHN-VPQH, 142/2026/VBHN-LQ-VPQH
RE_SO = re.compile(
    r"(?<![\w/])(\d{1,4}/(?:\d{4}/)?(?:[A-ZĐ]{1,10}\d{0,2})(?:-[A-ZĐ]{1,10}\d{0,2}){0,4})(?![\w/])"
)
_LOAI = r"(?:Bộ luật|Luật|Pháp lệnh|Nghị quyết|Nghị định|Quyết định|Thông tư liên tịch|Thông tư|Chỉ thị|Lệnh)"
RE_VI_TRI = re.compile(
    r"((?:(?:điểm|Điểm)\s+[a-zđ](?:\s*[,và]+\s*(?:điểm\s+)?[a-zđ](?![\w]))*\s+)?"
    r"(?:(?:khoản|Khoản)\s+\d+[a-zđ]?(?:\s*(?:,|và)\s*(?:khoản\s+)?\d+[a-zđ]?)*\s+(?:của\s+)?)?"
    r"(?:Điều|điều)\s+\d+[a-zđ]?)"
)
RE_DIEU = re.compile(r"(?:Điều|điều)\s+(\d+[a-zđ]?)")

RE_LENH_SUA = re.compile(
    r"^\s*(?:\d+[a-zđ]?\.|[a-zđ]\))?\s*(Sửa đổi, bổ sung|Sửa đổi|Bổ sung|Bãi bỏ|Thay thế|Thay cụm từ|Thay|Đính chính|Điều chỉnh)\b"
)
RE_DIEU_HIEU_LUC = re.compile(r"hiệu lực|thi hành|tổ chức thực hiện|chuyển tiếp", re.I)


@dataclass
class QuanHe:
    loai: str
    dst_so: str
    dst_vi_tri: str | None
    src_vi_tri: str | None
    can_cu_cau: str


def _cat(s: str, n: int = 300) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def tach_so(text: str) -> list[str]:
    return [m.group(1) for m in RE_SO.finditer(text) if "-" in m.group(1) or re.search(r"QH|UBTVQH", m.group(1))]


def _ngoai_ngoac_kep(lines: list[str]) -> list[tuple[int, str]]:
    """Các dòng (kèm vị trí) không nằm trong đoạn trích dẫn bằng ngoặc kép.
    Trong một dòng, đoạn trích trọn vẹn (mở và đóng trên cùng dòng) được thay bằng '“…”';
    từ dấu mở ngoặc chưa đóng trở đi bị bỏ."""
    out: list[tuple[int, str]] = []
    trong = False
    for i, line in enumerate(lines):
        if not trong:
            gon = re.sub(r"“[^“”]*”", "“…”", line)
            gon = re.sub(r'"[^"]*"', "“…”", gon)
            cut = [p for p in (gon.find("“", 0), gon.find('"')) if p >= 0]
            mo = [p for p in cut if gon[p:p + 3] != "“…”"]
            out.append((i, gon[: min(mo)] if mo else gon))
            trong = bool(mo)
            if trong and ("”" in gon[min(mo):] or gon[min(mo):].count('"') >= 2):
                trong = False
        else:
            if "”" in line or line.count('"') % 2 == 1:
                trong = False
    return out


RE_TOKEN = re.compile(
    r"(?P<diem>(?:điểm|Điểm)\s+[a-zđ](?![\w])(?:\s*(?:,|và)\s*(?:điểm\s+)?[a-zđ](?![\w]))*)"
    r"|(?P<khoan>(?:khoản|Khoản)\s+\d+[a-zđ]?(?:\s*(?:,|và)\s*(?:khoản\s+)?\d+[a-zđ]?(?![\w]))*)"
    r"|(?P<dieu>(?:Điều|điều)\s+\d+[a-zđ]?)"
)


def _vi_tri_trong(text: str, dieu_mac_dinh: str | None = None) -> list[str]:
    """'Bổ sung điểm c vào khoản 2; sửa đổi khoản 5, khoản 11 Điều 3'
    -> ['điểm c khoản 2 Điều 3', 'khoản 5 Điều 3', 'khoản 11 Điều 3']; 'Điều 6' -> ['Điều 6'].
    Cụm không có 'Điều' thì dùng dieu_mac_dinh (Điều nêu ở dòng lệnh cha)."""
    out: list[str] = []
    cho_diem: list[str] = []
    cho_khoan: list[tuple[str, list[str]]] = []

    def xa(dieu: str) -> None:
        for k, ds in cho_khoan:
            out.extend([f"điểm {d} khoản {k} Điều {dieu}" for d in ds] or [f"khoản {k} Điều {dieu}"])

    for m in RE_TOKEN.finditer(text):
        if m.group("diem"):
            cho_diem += re.findall(r"(?<![\w])[a-zđ](?![\w])", m.group("diem").split(None, 1)[1])
        elif m.group("khoan"):
            ks = re.findall(r"\d+[a-zđ]?", m.group("khoan"))
            for i, k in enumerate(ks):
                cho_khoan.append((k, cho_diem if i == 0 else []))
            cho_diem = []
        else:
            dieu = m.group("dieu").split()[1]
            if cho_khoan:
                xa(dieu)
            else:
                out.append(f"Điều {dieu}")
            cho_khoan, cho_diem = [], []
    if cho_khoan and dieu_mac_dinh:
        xa(dieu_mac_dinh)
    seen: list[str] = []
    for v in out:
        if v not in seen:
            seen.append(v)
    return seen


def _loai_tu_dong_tu(dong_tu: str) -> str:
    d = bo_dau(dong_tu)
    if d.startswith("bai bo"):
        return "bai_bo"
    if d.startswith("dinh chinh"):
        return "dinh_chinh"
    return "sua_doi"


def doc_sua_doi(dieu_so: str, dieu_text: str, so_dich_mac_dinh: str | None) -> list[QuanHe]:
    """Đọc lệnh sửa đổi trong một Điều của văn bản sửa đổi."""
    lines = dieu_text.split("\n")
    tieu_de = lines[0] if lines else ""
    so_tieu_de = tach_so(tieu_de)
    so_dich = so_tieu_de[0] if so_tieu_de else so_dich_mac_dinh
    out: list[QuanHe] = []
    dieu_cha: str | None = None
    for i, line in _ngoai_ngoac_kep(lines):
        if i == 0:
            continue
        m = RE_LENH_SUA.match(line)
        if not m:
            continue
        cau = re.split(r"\bnhư sau\b|:", line)[0]
        so_trong = tach_so(cau)
        dich = so_trong[0] if so_trong else so_dich
        if not dich:
            continue
        # Chỉ lấy phần vị trí trước tên văn bản đích (nếu có)
        truoc = re.split(_LOAI + r"\s+số", cau)[0] if so_trong else cau
        la_cha = bool(re.match(r"^\s*\d+[a-zđ]?\.", line))
        vts = _vi_tri_trong(truoc, None if la_cha else dieu_cha)
        if la_cha:
            ds = RE_DIEU.findall(truoc)
            dieu_cha = ds[-1] if ds else None
        loai = _loai_tu_dong_tu(m.group(1))
        if bo_dau(m.group(1)).startswith("thay") and not vts:
            continue
        for vt in vts or [None]:
            out.append(QuanHe(loai, dich, vt, f"Điều {dieu_so}", _cat(line)))
    return out


def doc_hieu_luc(dieu_so: str, dieu_text: str) -> list[QuanHe]:
    """Đọc điều khoản hiệu lực: văn bản nào bị thay thế, bãi bỏ, hết hiệu lực."""
    out: list[QuanHe] = []
    dong_tu_ds: str | None = None  # động từ của danh sách đang mở ("các văn bản sau đây hết hiệu lực:")
    for line in dieu_text.split("\n")[1:]:
        if re.match(r"^\s*\d+[a-zđ]?\.", line):
            dong_tu_ds = None
        if re.search(r"tiếp tục", line, re.I):
            continue
        dt = None
        if re.search(r"thay thế", line, re.I):
            dt = "thay_the"
        elif re.search(r"bãi bỏ", line, re.I):
            dt = "bai_bo"
        elif re.search(r"hết hiệu lực", line, re.I):
            dt = "het_hieu_luc"
        if line.rstrip().endswith(":") and dt:
            dong_tu_ds = dt
            so_ds = tach_so(line)
            if not so_ds:
                continue
        loai = dt or (dong_tu_ds if re.match(r"^\s*[a-zđ]\)|^\s*[-–+]", line) else None)
        if not loai:
            continue
        for muc in re.split(r";", line):
            so_ds = tach_so(muc)
            if not so_ds:
                continue
            so = so_ds[0]  # số đầu tiên là văn bản bị tác động; các số sau thuộc phần mô tả
            truoc = muc[: muc.find(so)]
            vt = None
            m = list(RE_VI_TRI.finditer(truoc[-80:]))
            if m and re.search(_LOAI + r"\s+(?:số\s+)?$", truoc.strip() + " "):
                vt = m[-1].group(1)
            out.append(QuanHe(loai, so, vt, f"Điều {dieu_so}", _cat(muc)))
    return out


def doc_van_ban(conn: sqlite3.Connection, doc: sqlite3.Row) -> list[QuanHe]:
    units = conn.execute(
        "SELECT loai, so, tieu_de, noi_dung, duong_dan FROM units WHERE doc_id = ? ORDER BY thu_tu", (doc["id"],)
    ).fetchall()
    ban_than = chuan_hoa_so_ky_hieu(doc["so_ky_hieu"])
    ty = doc["trich_yeu"] or ""
    out: list[QuanHe] = []

    so_ty = [s for s in tach_so(ty) if chuan_hoa_so_ky_hieu(s) != ban_than]
    la_sua_doi = bool(re.search(r"sửa đổi|bổ sung|bãi bỏ", ty, re.I))
    so_dich_mac_dinh = so_ty[0] if (la_sua_doi and len(so_ty) == 1) else None

    for u in units:
        if u["loai"] == "mo_dau":
            if doc["la_hop_nhat"]:
                for line in u["noi_dung"].split("\n"):
                    if line.strip().startswith("Căn cứ"):
                        continue
                    for s in tach_so(line):
                        if chuan_hoa_so_ky_hieu(s) != ban_than:
                            out.append(QuanHe("hop_nhat", s, None, None, _cat(line)))
            else:
                for line in u["noi_dung"].split("\n"):
                    if line.strip().startswith("Căn cứ"):
                        ds = tach_so(line)
                        if ds:
                            out.append(QuanHe("can_cu", ds[0], None, None, _cat(line)))
        elif u["loai"] == "dieu" and u["duong_dan"].count("Điều") == 1 and not doc["la_hop_nhat"]:
            tieu_de = u["tieu_de"] or ""
            if RE_DIEU_HIEU_LUC.search(tieu_de):
                out += doc_hieu_luc(u["so"], u["noi_dung"])
            elif la_sua_doi or re.search(r"sửa đổi|bổ sung|bãi bỏ", tieu_de, re.I):
                out += doc_sua_doi(u["so"], u["noi_dung"], so_dich_mac_dinh)

    co_vi_tri = {q.dst_so for q in out if q.loai in ("sua_doi", "bai_bo") and q.dst_vi_tri}
    if not doc["la_hop_nhat"]:
        if la_sua_doi:
            for s in so_ty:
                if s not in co_vi_tri:
                    out.append(QuanHe("sua_doi", s, None, None, _cat(ty)))
        if re.match(r"\s*(Quy định chi tiết|Hướng dẫn)", ty, re.I):
            for s in so_ty:
                out.append(QuanHe("huong_dan", s, None, None, _cat(ty)))

    # bỏ trùng, bỏ tự trỏ về chính mình
    seen = set()
    res = []
    for q in out:
        key = (q.loai, chuan_hoa_so_ky_hieu(q.dst_so), q.dst_vi_tri)
        if key in seen or chuan_hoa_so_ky_hieu(q.dst_so) == ban_than:
            continue
        seen.add(key)
        res.append(q)
    return res


def ghi_quan_he(conn: sqlite3.Connection, doc_ids: list[int] | None = None) -> dict[int, list[QuanHe]]:
    """Đọc lại và ghi quan hệ tự đọc cho các văn bản (mặc định: tất cả). Trả về {doc_id: [QuanHe]}."""
    from .store import _link_relations

    if doc_ids is None:
        docs = conn.execute("SELECT * FROM documents").fetchall()
    else:
        docs = [conn.execute("SELECT * FROM documents WHERE id = ?", (i,)).fetchone() for i in doc_ids]
    ket_qua: dict[int, list[QuanHe]] = {}
    for doc in docs:
        if doc is None:
            continue
        conn.execute("DELETE FROM relations WHERE src_doc_id = ? AND ghi_chu LIKE ?", (doc["id"], f"%{TU_DOC}%"))
        qs = doc_van_ban(conn, doc)
        for q in qs:
            conn.execute(
                "INSERT INTO relations (src_doc_id, loai_quan_he, dst_so_ky_hieu, src_vi_tri, dst_vi_tri, ghi_chu)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (doc["id"], q.loai, q.dst_so, q.src_vi_tri, q.dst_vi_tri, f"{TU_DOC} {q.can_cu_cau}"),
            )
        ket_qua[doc["id"]] = qs
    _link_relations(conn, None)
    conn.commit()
    return ket_qua
