"""Logic của 7 chức năng tra cứu. Mỗi hàm trả về chữ để Claude đọc.

Nguyên tắc chung:
- Luôn kèm số ký hiệu, cơ quan ban hành, tình trạng hiệu lực và nguồn.
- Không tìm thấy đúng văn bản thì nói "không tìm thấy", không đưa văn bản gần giống.
- Số ký hiệu trùng nhiều cơ quan thì liệt kê để chọn, không tự chọn.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date

from . import status as st
from .store import find_documents
from .textnorm import bo_dau

TRANG_KY_TU = 15000  # độ dài mỗi trang khi lấy toàn văn

STOPWORDS = set(
    "va cua la co cac nhung duoc cho trong khi thi neu de voi tu theo ve tai nay do mot hoac "
    "khong phai se da dang bi nhu ra vao len hay thuoc ma toi ban chung toi minh co the".split()
)

QUAN_HE_TEN = {
    "can_cu": "căn cứ",
    "huong_dan": "hướng dẫn",
    "sua_doi": "sửa đổi, bổ sung",
    "thay_the": "thay thế",
    "bai_bo": "bãi bỏ",
    "dinh_chinh": "đính chính",
    "hop_nhat": "hợp nhất",
    "tiep_tuc_ap_dung": "tiếp tục áp dụng sau sắp xếp",
    "het_hieu_luc": "làm hết hiệu lực",
}


# ---------------------------------------------------------------------------
# Tiện ích


def _nhan_tu_doc(r) -> str:
    """Ghi chú cho quan hệ đọc tự động từ nội dung văn bản."""
    try:
        gc = r["ghi_chu"] or ""
    except (IndexError, KeyError):
        return ""
    return " [tự đọc từ nội dung, cần đối chiếu]" if "tự đọc" in gc else ""


def _tinh_trang(doc: sqlite3.Row, hom_nay: date | None = None) -> tuple[str, str | None]:
    return st.tinh_trang(dict(doc), hom_nay)


def _d(iso: str | None) -> str:
    """'2025-07-01' -> '01/07/2025'."""
    if not iso:
        return "chưa rõ"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", iso)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else iso


def _ten(doc: sqlite3.Row) -> str:
    loai = doc["loai_van_ban"] or "Văn bản"
    ty = doc["trich_yeu"] or ""
    if ty and bo_dau(ty).startswith(bo_dau(loai)):
        return ty
    return f"{loai} {ty}".strip()


def _the_van_ban(doc: sqlite3.Row, hom_nay: date | None = None) -> str:
    tt, ly_do = _tinh_trang(doc, hom_nay)
    lines = [
        f"{_ten(doc)}",
        f"Số ký hiệu: {doc['so_ky_hieu']} | Cơ quan ban hành: {doc['co_quan_ban_hanh'] or 'chưa rõ'}",
        f"Ngày ban hành: {_d(doc['ngay_ban_hanh'])} | Ngày hiệu lực: {_d(doc['ngay_hieu_luc'])}"
        + (f" | Ngày hết hiệu lực: {_d(doc['ngay_het_hieu_luc'])}" if doc["ngay_het_hieu_luc"] else ""),
        f"Tình trạng hiệu lực: {tt}"
        + (f" (kiểm tra với nguồn ngày {_d(doc['ngay_kiem_tra'])})" if doc["ngay_kiem_tra"] else ""),
    ]
    if ly_do:
        lines.append(f"Lưu ý hiệu lực: {ly_do}")
    if doc["la_hop_nhat"]:
        lines.append(
            "Đây là văn bản hợp nhất: dùng để tra cứu; khi viện dẫn cần nêu văn bản gốc và văn bản sửa đổi, bổ sung."
        )
    if doc["tinh_ban_hanh_goc"] and doc["tinh_hien_nay"] and doc["tinh_ban_hanh_goc"] != doc["tinh_hien_nay"]:
        lines.append(
            f"Văn bản của tỉnh {doc['tinh_ban_hanh_goc']} trước sắp xếp; nay thuộc {doc['tinh_hien_nay']}."
            + (f" Phạm vi áp dụng: {doc['pham_vi_ap_dung']}." if doc["pham_vi_ap_dung"] else "")
        )
    if doc["thieu_phu_luc"]:
        lines.append("Phụ lục chưa có trong bản đang lưu, cần đối chiếu bản gốc trên Công báo.")
    if doc["canh_bao"]:
        lines.append(f"Cảnh báo: {doc['canh_bao']}")
    src = doc["nguon"] or "chưa rõ"
    lines.append(
        f"Nguồn: {src}"
        + (f" – {doc['url_goc']}" if doc["url_goc"] else "")
        + (f" (thu thập ngày {_d(doc['ngay_thu_thap'])})" if doc["ngay_thu_thap"] else "")
    )
    return "\n".join(lines)


def _resolve(conn, van_ban: str, co_quan: str | None) -> tuple[sqlite3.Row | None, str | None]:
    rows = find_documents(conn, van_ban, co_quan)
    if not rows:
        return None, (
            f"Không tìm thấy văn bản '{van_ban}' trong kho"
            + (f" (cơ quan: {co_quan})" if co_quan else "")
            + ". Không có văn bản thay thế được đề xuất."
        )
    if len(rows) > 1:
        rows = sorted(rows, key=lambda r: (r["la_hop_nhat"] or 0, r["ngay_ban_hanh"] or ""), reverse=True)
        ds = "\n".join(f"- {r['so_ky_hieu']} | {r['co_quan_ban_hanh']} | {_ten(r)}" for r in rows[:20])
        return None, (
            f"Có {len(rows)} văn bản khớp '{van_ban}'. Hãy chọn lại bằng số ký hiệu và cơ quan ban hành:\n{ds}"
        )
    return rows[0], None


def _fts_query(text: str, mode: str = "and") -> str | None:
    toks = [t for t in re.split(r"[^0-9a-z]+", bo_dau(text)) if t]
    if mode == "or":
        toks = [t for t in toks if t not in STOPWORDS and len(t) > 1]
    if not toks:
        return None
    joiner = " OR " if mode == "or" else " "
    return joiner.join(f'"{t}"' for t in toks)


def _trich_dong(noi_dung: str, query: str, max_len: int = 300) -> str:
    toks = [t for t in re.split(r"[^0-9a-z]+", bo_dau(query)) if t and t not in STOPWORDS]
    best, score = "", -1
    for line in noi_dung.split("\n"):
        n = bo_dau(line)
        sc = sum(1 for t in toks if t in n)
        if sc > score and line.strip():
            best, score = line.strip(), sc
    return best[:max_len] + ("…" if len(best) > max_len else "")


def _con_hieu_luc_hoac_khong_ro(doc, bao_gom_het: bool) -> bool:
    if bao_gom_het:
        return True
    tt, _ = _tinh_trang(doc)
    return tt != st.HET_TOAN_BO


# ---------------------------------------------------------------------------
# Phạm vi trung ương / địa phương

PHAM_VI = ("mac_dinh", "trung_uong", "dia_phuong", "tat_ca")
_RE_CQ_DIA_PHUONG = re.compile(r"\b(hdnd|ubnd|hoi dong nhan dan|uy ban nhan dan)\b")


def la_dia_phuong(doc) -> bool:
    """Văn bản của chính quyền địa phương (HĐND, UBND hoặc có ghi tỉnh)."""
    if doc["tinh_hien_nay"] or doc["tinh_ban_hanh_goc"]:
        return True
    return bool(_RE_CQ_DIA_PHUONG.search(bo_dau(doc["co_quan_ban_hanh"] or "")))


def _khop_tinh(doc, tinh: str) -> bool:
    return bo_dau(tinh) in bo_dau(
        f"{doc['tinh_ban_hanh_goc'] or ''} {doc['tinh_hien_nay'] or ''} {doc['co_quan_ban_hanh'] or ''}"
    )


def _dat_pham_vi(conn, pham_vi: str, tinh: str | None) -> str:
    """Ghi bảng tạm _pv gồm id văn bản được tìm, trả về điều kiện SQL cho units_fts (hoặc '').

    mac_dinh: không nêu tỉnh thì chỉ văn bản trung ương; nêu tỉnh thì trung ương + văn bản của tỉnh đó.
    trung_uong / dia_phuong: đúng một loại (dia_phuong kèm tỉnh thì chỉ tỉnh đó). tat_ca: không giới hạn.
    """
    if pham_vi not in PHAM_VI:
        raise ValueError(f"pham_vi phải là một trong {', '.join(PHAM_VI)}")
    if pham_vi == "tat_ca" and not tinh:
        return ""
    ids = []
    for d in conn.execute("SELECT id, co_quan_ban_hanh, tinh_hien_nay, tinh_ban_hanh_goc FROM documents"):
        dp = la_dia_phuong(d)
        if pham_vi == "trung_uong":
            ok = not dp
        elif pham_vi == "dia_phuong":
            ok = dp and (not tinh or _khop_tinh(d, tinh))
        elif pham_vi == "tat_ca":
            ok = not dp or _khop_tinh(d, tinh)
        else:  # mac_dinh
            ok = not dp or (bool(tinh) and _khop_tinh(d, tinh))
        if ok:
            ids.append((d["id"],))
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _pv (id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM _pv")
    conn.executemany("INSERT INTO _pv VALUES (?)", ids)
    return " AND f.doc_id IN (SELECT id FROM _pv)"


def _ghi_chu_dia_phuong(conn, q: str, pham_vi: str, tinh: str | None) -> str:
    """Nhắc khi tìm mặc định mà có văn bản địa phương khớp nhưng không hiển thị."""
    if pham_vi != "mac_dinh" or tinh:
        return ""
    n = 0
    seen: set[int] = set()
    for h in conn.execute("SELECT DISTINCT f.doc_id FROM units_fts f WHERE units_fts MATCH ? LIMIT 2000", (q,)):
        if h["doc_id"] in seen:
            continue
        seen.add(h["doc_id"])
        d = conn.execute(
            "SELECT co_quan_ban_hanh, tinh_hien_nay, tinh_ban_hanh_goc FROM documents WHERE id = ?", (h["doc_id"],)
        ).fetchone()
        if d and la_dia_phuong(d):
            n += 1
    if not n:
        return ""
    return (
        f"\n\n(Ngoài ra có {n} văn bản địa phương khớp từ khóa, không hiển thị. "
        "Nêu tinh=... hoặc pham_vi='dia_phuong' để xem.)"
    )


# ---------------------------------------------------------------------------
# 1. Tìm văn bản


def tim_van_ban(
    conn,
    tu_khoa: str,
    loai_van_ban: str | None = None,
    co_quan: str | None = None,
    tinh: str | None = None,
    linh_vuc: str | None = None,
    tu_ngay: str | None = None,
    den_ngay: str | None = None,
    bao_gom_het_hieu_luc: bool = False,
    gioi_han: int = 10,
    pham_vi: str = "mac_dinh",
) -> str:
    # Hỏi bằng số ký hiệu: chỉ trả về khớp đúng (mọi phạm vi).
    if re.search(r"\d+/\d{4}/|\d+/[A-ZĐ]", tu_khoa):
        rows = find_documents(conn, tu_khoa, co_quan)
        if not rows:
            return f"Không tìm thấy văn bản số '{tu_khoa}' trong kho."
        return "\n\n".join(_the_van_ban(r) for r in rows)

    q = _fts_query(tu_khoa)
    if not q:
        return "Từ khóa trống."
    dk = _dat_pham_vi(conn, pham_vi, tinh)
    sql = (
        "SELECT f.unit_id, f.doc_id, bm25(units_fts) AS rank FROM units_fts f "
        f"WHERE units_fts MATCH ?{dk} ORDER BY rank LIMIT 400"
    )
    hits = conn.execute(sql, (q,)).fetchall()
    # Thêm văn bản khớp theo tên/trích yếu.
    name_rows = find_documents(conn, tu_khoa) if "/" not in tu_khoa else []
    if dk:
        cho_phep = {r[0] for r in conn.execute("SELECT id FROM _pv")}
        name_rows = [r for r in name_rows if r["id"] in cho_phep]

    best: dict[int, tuple[float, int | None]] = {}
    for r in sorted(name_rows, key=lambda r: (r["la_hop_nhat"] or 0, r["ngay_ban_hanh"] or ""), reverse=True):
        best[r["id"]] = (-1e9 + len(best), None)  # khớp tên xếp đầu, văn bản hợp nhất mới nhất trước
    for h in hits:
        cur = best.get(h["doc_id"])
        if cur is None or (cur[0] > -1e8 and h["rank"] < cur[0]):
            best[h["doc_id"]] = (h["rank"], h["unit_id"])
        elif cur[1] is None:
            best[h["doc_id"]] = (cur[0], h["unit_id"])

    out = []
    for doc_id, (rank, unit_id) in sorted(best.items(), key=lambda kv: kv[1][0]):
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not _con_hieu_luc_hoac_khong_ro(doc, bao_gom_het_hieu_luc):
            continue
        if loai_van_ban and bo_dau(loai_van_ban) not in bo_dau(doc["loai_van_ban"] or ""):
            continue
        if co_quan and bo_dau(co_quan) not in (doc["co_quan_norm"] or ""):
            continue
        if tinh and pham_vi == "dia_phuong" and not _khop_tinh(doc, tinh):
            continue
        if linh_vuc and bo_dau(linh_vuc) not in bo_dau(doc["linh_vuc"] or ""):
            continue
        if tu_ngay and (doc["ngay_ban_hanh"] or "") < tu_ngay:
            continue
        if den_ngay and (doc["ngay_ban_hanh"] or "9999") > den_ngay:
            continue
        block = _the_van_ban(doc)
        if unit_id:
            u = conn.execute("SELECT duong_dan, noi_dung FROM units WHERE id = ?", (unit_id,)).fetchone()
            block += f"\nKhớp nhất tại: {u['duong_dan']}\nTrích: {_trich_dong(u['noi_dung'], tu_khoa)}"
        out.append(block)
        if len(out) >= gioi_han:
            break
    if not out:
        return f"Không tìm thấy văn bản phù hợp với '{tu_khoa}'" + (
            "" if bao_gom_het_hieu_luc else " trong số văn bản chưa hết hiệu lực toàn bộ"
        ) + "." + _ghi_chu_dia_phuong(conn, q, pham_vi, tinh)
    return f"Tìm thấy {len(out)} văn bản:\n\n" + "\n\n---\n\n".join(out) + _ghi_chu_dia_phuong(conn, q, pham_vi, tinh)


# ---------------------------------------------------------------------------
# 2. Xem mục lục


def xem_muc_luc(conn, van_ban: str, co_quan: str | None = None) -> str:
    doc, err = _resolve(conn, van_ban, co_quan)
    if err:
        return err
    rows = conn.execute(
        "SELECT loai, so, tieu_de, duong_dan FROM units WHERE doc_id = ? "
        "AND loai IN ('phan','chuong','muc','tieu_muc','dieu','phu_luc') ORDER BY thu_tu",
        (doc["id"],),
    ).fetchall()
    indent = {"phan": 0, "chuong": 0, "muc": 1, "tieu_muc": 2, "dieu": 2, "phu_luc": 0}
    ten = {"phan": "Phần", "chuong": "Chương", "muc": "Mục", "tieu_muc": "Tiểu mục", "dieu": "Điều", "phu_luc": "Phụ lục"}
    lines = []
    for r in rows:
        label = f"{ten[r['loai']]} {r['so'] or ''}".strip()
        sep = ". " if r["loai"] == "dieu" else (": " if r["tieu_de"] else "")
        lines.append("  " * indent[r["loai"]] + label + sep + (r["tieu_de"] or ""))
    n_dieu = sum(1 for r in rows if r["loai"] == "dieu")
    return _the_van_ban(doc) + f"\n\nMục lục ({n_dieu} điều):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Lấy toàn văn


def lay_toan_van(conn, van_ban: str, co_quan: str | None = None, trang: int = 1) -> str:
    doc, err = _resolve(conn, van_ban, co_quan)
    if err:
        return err
    tops = conn.execute(
        "SELECT noi_dung FROM units WHERE doc_id = ? AND parent_id IS NULL ORDER BY thu_tu",
        (doc["id"],),
    ).fetchall()
    full = "\n".join(t["noi_dung"] for t in tops)
    pages: list[str] = []
    cur = ""
    for line in full.split("\n"):
        if len(cur) + len(line) + 1 > TRANG_KY_TU and cur:
            pages.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        pages.append(cur)
    tong = max(len(pages), 1)
    if trang < 1 or trang > tong:
        return f"Văn bản có {tong} trang; trang {trang} không tồn tại."
    head = _the_van_ban(doc) + f"\n\nToàn văn – trang {trang}/{tong}:\n\n"
    tail = f"\n\n[Còn {tong - trang} trang, gọi lại với trang={trang + 1}]" if trang < tong else ""
    return head + (pages[trang - 1] if pages else "") + tail


# ---------------------------------------------------------------------------
# 4. Tra cứu tuân thủ


def tra_cuu_tuan_thu(
    conn,
    tinh_huong: str,
    linh_vuc: str | None = None,
    gioi_han: int = 8,
    tinh: str | None = None,
    pham_vi: str = "mac_dinh",
) -> str:
    q = _fts_query(tinh_huong, mode="or")
    if not q:
        return "Mô tả tình huống trống."
    dk = _dat_pham_vi(conn, pham_vi, tinh)
    hits = conn.execute(
        "SELECT f.unit_id, f.doc_id, bm25(units_fts) AS rank FROM units_fts f "
        f"WHERE units_fts MATCH ?{dk} ORDER BY rank LIMIT 200",
        (q,),
    ).fetchall()
    out = []
    for h in hits:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (h["doc_id"],)).fetchone()
        tt, _ = _tinh_trang(doc)
        if tt in (st.HET_TOAN_BO, st.CHUA_HIEU_LUC):
            continue
        if linh_vuc and bo_dau(linh_vuc) not in bo_dau(doc["linh_vuc"] or ""):
            continue
        u = conn.execute("SELECT duong_dan, noi_dung FROM units WHERE id = ?", (h["unit_id"],)).fetchone()
        text = u["noi_dung"]
        if len(text) > 4000:
            text = text[:4000] + "\n[…đã rút gọn, dùng trich_dieu_khoan để lấy đủ]"
        out.append(
            f"### {doc['so_ky_hieu']} ({doc['co_quan_ban_hanh']}) – {u['duong_dan']}\n"
            f"Tình trạng: {tt}\n\n{text}"
        )
        if len(out) >= gioi_han:
            break
    if not out:
        return "Không tìm thấy quy định liên quan trong các văn bản đang có hiệu lực trong kho."
    return (
        "Các trích đoạn nguyên văn dưới đây là quy định liên quan nhất tìm được. "
        "Đây là dữ liệu để phân tích, công cụ không tự kết luận về việc tuân thủ.\n\n"
        + "\n\n".join(out)
    )


# ---------------------------------------------------------------------------
# 5. Trích Điều/Khoản/Điểm


def _anh_huong(conn, doc_id: int, dieu: str, khoan: str | None) -> list[str]:
    rows = conn.execute(
        "SELECT r.*, d.so_ky_hieu AS src_so, d.co_quan_ban_hanh AS src_cq FROM relations r "
        "JOIN documents d ON d.id = r.src_doc_id WHERE r.dst_doc_id = ? "
        "AND r.loai_quan_he IN ('sua_doi','thay_the','bai_bo','dinh_chinh','het_hieu_luc')",
        (doc_id,),
    ).fetchall()
    out = []
    for r in rows:
        vt = bo_dau(r["dst_vi_tri"] or "")
        if not vt:
            if r["loai_quan_he"] in ("thay_the", "bai_bo", "het_hieu_luc"):
                out.append(
                    f"- Toàn bộ văn bản bị {QUAN_HE_TEN.get(r['loai_quan_he'], r['loai_quan_he'])} bởi "
                    f"{r['src_vi_tri'] + ' ' if r['src_vi_tri'] else ''}{r['src_so']} ({r['src_cq']})" + _nhan_tu_doc(r)
                )
            continue
        if not re.search(rf"\bdieu {re.escape(bo_dau(dieu))}\b", vt):
            continue
        if khoan and "khoan" in vt and not re.search(rf"\bkhoan {re.escape(khoan)}\b", vt):
            continue
        out.append(
            f"- {r['dst_vi_tri']} bị {QUAN_HE_TEN.get(r['loai_quan_he'], r['loai_quan_he'])} bởi "
            f"{r['src_vi_tri'] + ' ' if r['src_vi_tri'] else ''}{r['src_so']} ({r['src_cq']})" + _nhan_tu_doc(r)
        )
    return out


def trich_dieu_khoan(
    conn,
    van_ban: str,
    dieu: str,
    khoan: str | None = None,
    diem: str | None = None,
    co_quan: str | None = None,
) -> str:
    doc, err = _resolve(conn, van_ban, co_quan)
    if err:
        return err
    dieu = str(dieu).strip().lower().removeprefix("điều").strip()
    u = conn.execute(
        "SELECT * FROM units WHERE doc_id = ? AND loai = 'dieu' AND so = ? ORDER BY thu_tu",
        (doc["id"], dieu),
    ).fetchall()
    if not u:
        return _the_van_ban(doc) + f"\n\nVăn bản này không có Điều {dieu}."
    if len(u) > 1:
        # Ví dụ văn bản sửa đổi có trích lại 'Điều 5' của luật khác: lấy đơn vị cấp cao nhất.
        u = [x for x in u if x["duong_dan"].count("Điều") == 1] or u
    unit = u[0]
    nhan = f"Điều {dieu}"
    if khoan:
        k = conn.execute(
            "SELECT * FROM units WHERE parent_id = ? AND loai = 'khoan' AND so = ?",
            (unit["id"], str(khoan)),
        ).fetchone()
        if not k:
            return _the_van_ban(doc) + f"\n\nĐiều {dieu} không có khoản {khoan}."
        unit, nhan = k, f"khoản {khoan} Điều {dieu}"
    if diem:
        d = conn.execute(
            "SELECT * FROM units WHERE parent_id = ? AND loai = 'diem' AND so = ?",
            (unit["id"], str(diem).strip(") ")),
        ).fetchone()
        if not d:
            return _the_van_ban(doc) + f"\n\n{nhan} không có điểm {diem}."
        unit, nhan = d, f"điểm {diem} {nhan}"
    res = _the_van_ban(doc) + f"\n\nNguyên văn {nhan} ({unit['duong_dan']}):\n\n{unit['noi_dung']}"
    canh_bao = _anh_huong(conn, doc["id"], dieu, khoan)
    if canh_bao:
        res += "\n\nCẢNH BÁO – phần này đã bị tác động bởi văn bản khác:\n" + "\n".join(canh_bao)
    return res


# ---------------------------------------------------------------------------
# 6. Kiểm tra hiệu lực


def kiem_tra_hieu_luc(conn, danh_sach: list[str]) -> str:
    out = []
    for so in danh_sach:
        rows = find_documents(conn, so)
        if not rows:
            out.append(f"{so}: không có trong kho, chưa kiểm tra được.")
            continue
        for doc in rows:
            block = _the_van_ban(doc)
            thay = conn.execute(
                "SELECT d.so_ky_hieu, d.co_quan_ban_hanh, r.loai_quan_he, r.dst_vi_tri, r.ghi_chu FROM relations r "
                "JOIN documents d ON d.id = r.src_doc_id WHERE r.dst_doc_id = ? "
                "AND r.loai_quan_he IN ('thay_the','bai_bo','sua_doi','het_hieu_luc')",
                (doc["id"],),
            ).fetchall()
            if thay:
                block += "\nBị tác động bởi:\n" + "\n".join(
                    f"- {QUAN_HE_TEN[t['loai_quan_he']]}"
                    + (f" ({t['dst_vi_tri']})" if t["dst_vi_tri"] else "")
                    + f": {t['so_ky_hieu']} ({t['co_quan_ban_hanh']})"
                    + _nhan_tu_doc(t)
                    for t in thay
                )
            out.append(block)
    return "\n\n---\n\n".join(out)


# ---------------------------------------------------------------------------
# 7. Văn bản liên quan


def van_ban_lien_quan(conn, van_ban: str, co_quan: str | None = None) -> str:
    doc, err = _resolve(conn, van_ban, co_quan)
    if err:
        return err
    di = conn.execute("SELECT * FROM relations WHERE src_doc_id = ?", (doc["id"],)).fetchall()
    den = conn.execute(
        "SELECT r.*, d.so_ky_hieu AS src_so, d.co_quan_ban_hanh AS src_cq FROM relations r "
        "JOIN documents d ON d.id = r.src_doc_id WHERE r.dst_doc_id = ?",
        (doc["id"],),
    ).fetchall()
    lines = [_the_van_ban(doc), ""]
    if di:
        lines.append("Văn bản này:")
        for r in di:
            lines.append(
                f"- {QUAN_HE_TEN.get(r['loai_quan_he'], r['loai_quan_he'])} {r['dst_so_ky_hieu']}"
                + (f" ({r['dst_vi_tri']})" if r["dst_vi_tri"] else "")
                + ("" if r["dst_doc_id"] else " [chưa có trong kho]")
                + _nhan_tu_doc(r)
            )
    if den:
        lines.append("Văn bản tác động đến văn bản này:")
        for r in den:
            lines.append(
                f"- {r['src_so']} ({r['src_cq']}) {QUAN_HE_TEN.get(r['loai_quan_he'], r['loai_quan_he'])}"
                + (f" {r['dst_vi_tri']}" if r["dst_vi_tri"] else "")
                + _nhan_tu_doc(r)
            )
    if not di and not den:
        lines.append("Chưa ghi nhận văn bản liên quan trong kho.")
    return "\n".join(lines)
