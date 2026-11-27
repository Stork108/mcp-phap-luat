"""Kho dữ liệu SQLite: văn bản, đơn vị nội dung (Điều/Khoản/Điểm), quan hệ.

Một tệp .db duy nhất, chạy được cả trên máy cá nhân và trên cloud.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Thông tin văn bản. Nhận diện bằng cặp (số ký hiệu chuẩn hóa, cơ quan chuẩn hóa)
-- vì số ký hiệu có thể trùng giữa nhiều cơ quan (nhất là văn bản địa phương).
CREATE TABLE IF NOT EXISTS documents (
    id                 INTEGER PRIMARY KEY,
    so_ky_hieu         TEXT NOT NULL,
    so_ky_hieu_norm    TEXT NOT NULL,
    loai_van_ban       TEXT,
    co_quan_ban_hanh   TEXT NOT NULL DEFAULT '',
    co_quan_norm       TEXT NOT NULL DEFAULT '',
    tinh_ban_hanh_goc  TEXT,          -- văn bản địa phương: tỉnh ban hành ban đầu
    tinh_hien_nay      TEXT,          -- tỉnh sau sắp xếp 2025
    pham_vi_ap_dung    TEXT,          -- ví dụ: 'địa bàn tỉnh Bình Dương trước sắp xếp'
    trich_yeu          TEXT,
    trich_yeu_norm     TEXT,
    ngay_ban_hanh      TEXT,          -- YYYY-MM-DD
    ngay_hieu_luc      TEXT,
    ngay_het_hieu_luc  TEXT,
    tinh_trang_nguon   TEXT,          -- tình trạng hiệu lực ghi tại nguồn
    ngay_kiem_tra      TEXT,          -- lần gần nhất đối chiếu tình trạng với nguồn
    linh_vuc           TEXT,
    la_hop_nhat        INTEGER NOT NULL DEFAULT 0,
    nguon              TEXT,          -- vbpl.vn, congbao, thu-vien-phap-luat, thu-cong...
    url_goc            TEXT,
    ngay_thu_thap      TEXT,
    canh_bao           TEXT,          -- cảnh báo hiển thị kèm kết quả
    thieu_phu_luc      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (so_ky_hieu_norm, co_quan_norm)
);
CREATE INDEX IF NOT EXISTS idx_doc_so ON documents (so_ky_hieu_norm);

-- Đơn vị nội dung. 'noi_dung' là NGUYÊN VĂN của cả đơn vị (Điều gồm cả các Khoản).
CREATE TABLE IF NOT EXISTS units (
    id         INTEGER PRIMARY KEY,
    doc_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_id  INTEGER REFERENCES units(id) ON DELETE CASCADE,
    loai       TEXT NOT NULL,   -- mo_dau, phan, chuong, muc, tieu_muc, dieu, khoan, diem, phu_luc, ket
    so         TEXT,            -- '5', 'IV', 'a'...
    tieu_de    TEXT,
    noi_dung   TEXT NOT NULL,
    thu_tu     INTEGER NOT NULL,
    duong_dan  TEXT NOT NULL    -- ví dụ: 'Chương II > Điều 5 > Khoản 3'
);
CREATE INDEX IF NOT EXISTS idx_units_doc ON units (doc_id, thu_tu);
CREATE INDEX IF NOT EXISTS idx_units_parent ON units (parent_id);

-- Quan hệ giữa văn bản (đến cấp Điều/Khoản khi xác định được).
CREATE TABLE IF NOT EXISTS relations (
    id              INTEGER PRIMARY KEY,
    src_doc_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    loai_quan_he    TEXT NOT NULL,  -- can_cu, huong_dan, sua_doi, thay_the, bai_bo, dinh_chinh, hop_nhat, tiep_tuc_ap_dung, het_hieu_luc
    dst_so_ky_hieu  TEXT NOT NULL,  -- văn bản bị tác động / được dẫn chiếu
    dst_co_quan     TEXT,
    dst_doc_id      INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    src_vi_tri      TEXT,           -- 'Điều 1' của văn bản nguồn
    dst_vi_tri      TEXT,           -- 'khoản 3 Điều 5' của văn bản đích
    ghi_chu         TEXT
);
CREATE INDEX IF NOT EXISTS idx_rel_src ON relations (src_doc_id);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON relations (dst_doc_id);

-- Chỉ mục tìm kiếm toàn văn trên chữ đã bỏ dấu (tìm được cả có dấu và không dấu).
-- Chỉ đánh chỉ mục cấp Điều, phần mở đầu và phụ lục để tránh trùng kết quả.
CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5 (
    noi_dung_norm,
    unit_id UNINDEXED,
    doc_id UNINDEXED,
    tokenize = 'unicode61'
);

-- Nhật ký thay đổi (văn bản mới, đổi tình trạng...).
CREATE TABLE IF NOT EXISTS changelog (
    id        INTEGER PRIMARY KEY,
    thoi_diem TEXT NOT NULL,
    doc_id    INTEGER,
    su_kien   TEXT NOT NULL,
    chi_tiet  TEXT
);
"""


def default_db_path() -> Path:
    env = os.environ.get("PHAPLUAT_DB")
    if env:
        return Path(env)
    return Path.cwd() / "data" / "phapluat.db"


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
