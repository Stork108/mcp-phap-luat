"""Ghi văn bản đã tách cấu trúc vào kho và tra cứu văn bản."""

from __future__ import annotations

import re

import sqlite3
from datetime import datetime

from .parser import ParsedDocument
from .textnorm import bo_dau, chuan_hoa_so_ky_hieu, chuan_hoa_ten_co_quan

DOC_FIELDS = [
    "so_ky_hieu",
    "loai_van_ban",
    "co_quan_ban_hanh",
    "tinh_ban_hanh_goc",
    "tinh_hien_nay",
    "pham_vi_ap_dung",
    "trich_yeu",
    "ngay_ban_hanh",
    "ngay_hieu_luc",
    "ngay_het_hieu_luc",
    "tinh_trang_nguon",
    "ngay_kiem_tra",
    "linh_vuc",
    "la_hop_nhat",
    "nguon",
    "url_goc",
    "ngay_thu_thap",
    "canh_bao",
    "thieu_phu_luc",
]

# Chỉ đánh chỉ mục tìm kiếm các đơn vị này để kết quả không trùng lặp.
FTS_LOAI = {"dieu", "mo_dau", "phu_luc"}


def ten_day_du_norm(meta) -> str:
    """Tên đầy đủ đã bỏ dấu, ví dụ 'luat doanh nghiep', dùng để tìm theo tên."""
    loai = bo_dau(meta.get("loai_van_ban") or "")
    ty = bo_dau(meta.get("trich_yeu") or "")
    if loai and not ty.startswith(loai):
        return f"{loai} {ty}".strip()
    return ty


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(conn: sqlite3.Connection, doc_id: int | None, su_kien: str, chi_tiet: str = "") -> None:
    conn.execute(
        "INSERT INTO changelog (thoi_diem, doc_id, su_kien, chi_tiet) VALUES (?, ?, ?, ?)",
        (_now(), doc_id, su_kien, chi_tiet),
    )


def upsert_document(conn: sqlite3.Connection, meta: dict, parsed: ParsedDocument) -> int:
    """Thêm hoặc thay thế một văn bản. Trả về id văn bản."""
    if not meta.get("so_ky_hieu"):
        raise ValueError("Thiếu số ký hiệu văn bản.")
    meta = dict(meta)
    meta.setdefault("co_quan_ban_hanh", "")
    meta.setdefault("ngay_thu_thap", _now()[:10])
    meta["la_hop_nhat"] = int(bool(meta.get("la_hop_nhat")) or "VBHN" in meta["so_ky_hieu"].upper())
    meta["thieu_phu_luc"] = int(bool(meta.get("thieu_phu_luc")))
    so_norm = chuan_hoa_so_ky_hieu(meta["so_ky_hieu"])
    cq_norm = chuan_hoa_ten_co_quan(meta["co_quan_ban_hanh"])

    old = conn.execute(
        "SELECT * FROM documents WHERE so_ky_hieu_norm = ? AND co_quan_norm = ?",
        (so_norm, cq_norm),
    ).fetchone()

    cols = DOC_FIELDS + ["so_ky_hieu_norm", "co_quan_norm", "trich_yeu_norm"]
    values = [meta.get(f) for f in DOC_FIELDS] + [so_norm, cq_norm, ten_day_du_norm(meta)]

    if old is None:
        cur = conn.execute(
            f"INSERT INTO documents ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            values,
        )
        doc_id = cur.lastrowid
        log(conn, doc_id, "them_moi", meta["so_ky_hieu"])
    else:
        doc_id = old["id"]
        conn.execute(
            f"UPDATE documents SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
            values + [doc_id],
        )
        if (old["tinh_trang_nguon"] or "") != (meta.get("tinh_trang_nguon") or ""):
            log(
                conn,
                doc_id,
                "doi_tinh_trang",
                f"{old['tinh_trang_nguon']} -> {meta.get('tinh_trang_nguon')}",
            )
        else:
            log(conn, doc_id, "cap_nhat", meta["so_ky_hieu"])
        conn.execute("DELETE FROM units_fts WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM units WHERE doc_id = ?", (doc_id,))

    ids: dict[int, int] = {}
    for thu_tu, u in enumerate(parsed.walk()):
        parent_id = ids.get(id(u.parent)) if u.parent is not None else None
        cur = conn.execute(
            "INSERT INTO units (doc_id, parent_id, loai, so, tieu_de, noi_dung, thu_tu, duong_dan)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, parent_id, u.loai, u.so, u.tieu_de, u.noi_dung, thu_tu, u.duong_dan()),
        )
        ids[id(u)] = cur.lastrowid
        if u.loai in FTS_LOAI and u.noi_dung.strip():
            conn.execute(
                "INSERT INTO units_fts (noi_dung_norm, unit_id, doc_id) VALUES (?, ?, ?)",
                (bo_dau(u.noi_dung), cur.lastrowid, doc_id),
            )
    _link_relations(conn, doc_id)
    conn.commit()
    return doc_id


def add_relation(
    conn: sqlite3.Connection,
    src_doc_id: int,
    loai_quan_he: str,
    dst_so_ky_hieu: str,
    dst_co_quan: str | None = None,
    src_vi_tri: str | None = None,
    dst_vi_tri: str | None = None,
    ghi_chu: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO relations (src_doc_id, loai_quan_he, dst_so_ky_hieu, dst_co_quan,"
        " src_vi_tri, dst_vi_tri, ghi_chu) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_doc_id, loai_quan_he, dst_so_ky_hieu, dst_co_quan, src_vi_tri, dst_vi_tri, ghi_chu),
    )
    _link_relations(conn, None)
    conn.commit()


_RE_SO_DIA_PHUONG = re.compile(r"(HĐND|UBND|HDND)", re.I)


def _link_relations(conn: sqlite3.Connection, _doc_id: int | None) -> None:
    """Nối quan hệ với văn bản đích khi văn bản đích đã có trong kho (khớp duy nhất)."""
    rows = conn.execute(
        "SELECT r.id, r.dst_so_ky_hieu, r.dst_co_quan, d.tinh_hien_nay AS src_tinh FROM relations r "
        "LEFT JOIN documents d ON d.id = r.src_doc_id WHERE r.dst_doc_id IS NULL"
    ).fetchall()
    for r in rows:
        so = chuan_hoa_so_ky_hieu(r["dst_so_ky_hieu"])
        if r["dst_co_quan"]:
            cands = conn.execute(
                "SELECT id, tinh_hien_nay FROM documents WHERE so_ky_hieu_norm = ? AND co_quan_norm = ?",
                (so, chuan_hoa_ten_co_quan(r["dst_co_quan"])),
            ).fetchall()
        else:
            cands = conn.execute("SELECT id, tinh_hien_nay FROM documents WHERE so_ky_hieu_norm = ?", (so,)).fetchall()
        if len(cands) > 1 and r["src_tinh"] and _RE_SO_DIA_PHUONG.search(r["dst_so_ky_hieu"] or ""):
            # Số ký hiệu địa phương trùng giữa các tỉnh (ví dụ 28/2025/NQ-HĐND): văn bản địa phương
            # nhắc số không kèm tên tỉnh thì chỉ nối khi đúng một văn bản cùng tỉnh hiện nay.
            cands = [c for c in cands if c["tinh_hien_nay"] == r["src_tinh"]]
        if len(cands) == 1:
            conn.execute("UPDATE relations SET dst_doc_id = ? WHERE id = ?", (cands[0]["id"], r["id"]))


def find_documents(conn: sqlite3.Connection, query: str, co_quan: str | None = None) -> list[sqlite3.Row]:
    """Tìm văn bản theo số ký hiệu (khớp đúng) hoặc theo tên/trích yếu.

    Không bao giờ trả về văn bản 'gần giống' khi hỏi bằng số ký hiệu.
    """
    q = query.strip()
    so = chuan_hoa_so_ky_hieu(q)
    params: list = [so]
    sql = "SELECT * FROM documents WHERE so_ky_hieu_norm = ?"
    if co_quan:
        sql += " AND co_quan_norm LIKE ?"
        params.append(f"%{chuan_hoa_ten_co_quan(co_quan)}%")
    rows = conn.execute(sql, params).fetchall()
    if rows or "/" in q:
        return rows
    # Tìm theo tên: mọi từ của câu hỏi phải có trong trích yếu (hoặc tên đầy đủ).
    words = bo_dau(q).split()
    if not words:
        return []
    cond = " AND ".join(["trich_yeu_norm LIKE ?"] * len(words))
    params = [f"%{w}%" for w in words]
    sql = f"SELECT * FROM documents WHERE {cond}"
    if co_quan:
        sql += " AND co_quan_norm LIKE ?"
        params.append(f"%{chuan_hoa_ten_co_quan(co_quan)}%")
    rows = conn.execute(sql + " ORDER BY ngay_ban_hanh DESC", params).fetchall()
    # Ưu tiên khớp nguyên cụm
    full = bo_dau(q)
    exact = [r for r in rows if (r["trich_yeu_norm"] or "") == full]
    return exact or rows
