from datetime import date
from pathlib import Path

import pytest

from phapluat import tools
from phapluat.cli import nhap_tep
from phapluat.db import connect
from phapluat.parser import parse_text
from phapluat.store import add_relation, upsert_document

FIX = Path(__file__).parent / "fixtures" / "mau_nghi_dinh.txt"

LOCAL = """ỦY BAN NHÂN DÂN TỈNH {tinh}
Số: 01/2099/QĐ-UBND

QUYẾT ĐỊNH
Quy định mẫu của tỉnh {tinh}

Điều 1. Nội dung
Áp dụng trên địa bàn tỉnh {tinh}.
"""


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    nhap_tep(c, str(FIX), {"tinh_trang_nguon": "Còn hiệu lực", "nguon": "kiem-thu", "linh_vuc": "Lao động"})
    for tinh, goc in (("Bình Dương", "Bình Dương"), ("Đồng Nai", "Đồng Nai")):
        upsert_document(
            c,
            {
                "so_ky_hieu": "01/2099/QĐ-UBND",
                "co_quan_ban_hanh": f"Ủy ban nhân dân tỉnh {tinh}",
                "loai_van_ban": "Quyết định",
                "trich_yeu": f"Quy định mẫu của tỉnh {tinh}",
                "tinh_ban_hanh_goc": goc,
                "tinh_hien_nay": "TP. Hồ Chí Minh" if tinh == "Bình Dương" else "Đồng Nai",
                "ngay_hieu_luc": "2099-01-01",
                "tinh_trang_nguon": "Còn hiệu lực",
            },
            parse_text(LOCAL.format(tinh=tinh)),
        )
    # Văn bản sửa đổi khoản 2 Điều 3 của nghị định mẫu
    amend = upsert_document(
        c,
        {
            "so_ky_hieu": "1000/2099/NĐ-CP",
            "co_quan_ban_hanh": "Chính phủ",
            "loai_van_ban": "Nghị định",
            "trich_yeu": "Sửa đổi nghị định mẫu",
            "ngay_hieu_luc": "2099-06-01",
            "tinh_trang_nguon": "Còn hiệu lực",
        },
        parse_text("Điều 1. Sửa đổi khoản 2 Điều 3\nNội dung sửa đổi."),
    )
    add_relation(c, amend, "sua_doi", "999/2099/NĐ-CP", None, "Điều 1", "khoản 2 Điều 3")
    yield c
    c.close()


def test_status_uses_dates(conn, monkeypatch):
    # Năm 2099 chưa đến: nguồn ghi 'Còn hiệu lực' nhưng ngày hiệu lực chưa tới -> Cần kiểm tra
    out = tools.kiem_tra_hieu_luc(conn, ["999/2099/NĐ-CP"])
    assert "Tình trạng hiệu lực: Cần kiểm tra" in out
    assert "sửa đổi, bổ sung (khoản 2 Điều 3): 1000/2099/NĐ-CP" in out


def test_search_accent_insensitive(conn):
    out = tools.tim_van_ban(conn, "tro cap thoi viec", bao_gom_het_hieu_luc=True)
    assert "999/2099/NĐ-CP" in out
    assert "Điều 3" in out
    assert "Trích:" in out


def test_exact_number_only(conn):
    assert "Không tìm thấy" in tools.tim_van_ban(conn, "998/2099/NĐ-CP")
    assert "Không tìm thấy" in tools.xem_muc_luc(conn, "998/2099/NĐ-CP")


def test_duplicate_number_lists_both(conn):
    out = tools.xem_muc_luc(conn, "01/2099/QĐ-UBND")
    assert "Có 2 văn bản khớp" in out
    assert "Bình Dương" in out and "Đồng Nai" in out
    one = tools.xem_muc_luc(conn, "01/2099/QĐ-UBND", co_quan="Đồng Nai")
    assert "Có 2" not in one and "Đồng Nai" in one


def test_local_merger_note(conn):
    out = tools.xem_muc_luc(conn, "01/2099/QĐ-UBND", co_quan="Bình Dương")
    assert "Văn bản của tỉnh Bình Dương trước sắp xếp; nay thuộc TP. Hồ Chí Minh." in out


def test_quote_article_verbatim_with_warning(conn):
    out = tools.trich_dieu_khoan(conn, "999/2099/NĐ-CP", "3", khoan="2")
    assert "2. Mỗi năm làm việc được trợ cấp một nửa tháng tiền lương." in out
    assert "CẢNH BÁO" in out and "1000/2099/NĐ-CP" in out
    out = tools.trich_dieu_khoan(conn, "999/2099/NĐ-CP", "2", khoan="3", diem="b")
    assert out.rstrip().endswith("đ) Dòng này không đúng thứ tự nên không được nhận là điểm.")
    assert "không có khoản 9" in tools.trich_dieu_khoan(conn, "999/2099/NĐ-CP", "2", khoan="9")


def test_toc_and_fulltext(conn):
    toc = tools.xem_muc_luc(conn, "999/2099/NĐ-CP")
    assert "Mục lục (4 điều)" in toc and "Chương II: TRỢ CẤP" in toc
    full = tools.lay_toan_van(conn, "999/2099/NĐ-CP")
    assert "trang 1/1" in full and "PHỤ LỤC I" in full


def test_compliance_and_related(conn):
    out = tools.tra_cuu_tuan_thu(conn, "người lao động làm 12 tháng có được trợ cấp thôi việc không")
    # Văn bản 2099 chưa có hiệu lực -> vẫn trả về vì tình trạng 'Cần kiểm tra', không phải 'Chưa có hiệu lực'
    assert "Điều 3" in out
    rel = tools.van_ban_lien_quan(conn, "999/2099/NĐ-CP")
    assert "1000/2099/NĐ-CP" in rel


def test_status_logic():
    from phapluat.status import tinh_trang

    d = {"tinh_trang_nguon": "Còn hiệu lực", "ngay_hieu_luc": "2020-01-01"}
    assert tinh_trang(d, date(2026, 1, 1)) == ("Còn hiệu lực", None)
    d = {"tinh_trang_nguon": "Còn hiệu lực", "ngay_hieu_luc": "2020-01-01", "ngay_het_hieu_luc": "2025-07-01"}
    assert tinh_trang(d, date(2026, 1, 1))[0] == "Cần kiểm tra"
    d = {"tinh_trang_nguon": "Hết hiệu lực toàn bộ", "ngay_het_hieu_luc": "2025-07-01"}
    assert tinh_trang(d, date(2026, 1, 1))[0] == "Hết hiệu lực toàn bộ"
    assert tinh_trang({}, date(2026, 1, 1))[0] == "Cần kiểm tra"


def test_pham_vi_trung_uong_va_dia_phuong(conn):
    # Mặc định không nêu tỉnh: chỉ văn bản trung ương, kèm nhắc có văn bản địa phương khớp.
    out = tools.tim_van_ban(conn, "quy dinh mau", bao_gom_het_hieu_luc=True)
    assert "01/2099/QĐ-UBND" not in out
    assert "2 văn bản địa phương khớp" in out
    # Nêu tỉnh (cũ hoặc mới): thêm văn bản của đúng tỉnh đó.
    out = tools.tim_van_ban(conn, "quy dinh mau", tinh="Bình Dương", bao_gom_het_hieu_luc=True)
    assert "tỉnh Bình Dương" in out and "tỉnh Đồng Nai" not in out
    out = tools.tim_van_ban(conn, "quy dinh mau", tinh="Hồ Chí Minh", bao_gom_het_hieu_luc=True)
    assert "tỉnh Bình Dương" in out and "tỉnh Đồng Nai" not in out
    out = tools.tim_van_ban(conn, "quy dinh mau", pham_vi="dia_phuong", bao_gom_het_hieu_luc=True)
    assert "tỉnh Bình Dương" in out and "tỉnh Đồng Nai" in out
    out = tools.tim_van_ban(conn, "quy dinh mau", pham_vi="dia_phuong", tinh="Đồng Nai", bao_gom_het_hieu_luc=True)
    assert "tỉnh Đồng Nai" in out and "tỉnh Bình Dương" not in out and "999/2099/NĐ-CP" not in out
    # Tìm theo số ký hiệu: mọi phạm vi.
    assert "Đồng Nai" in tools.tim_van_ban(conn, "01/2099/QĐ-UBND")
    out = tools.tra_cuu_tuan_thu(conn, "áp dụng trên địa bàn tỉnh")
    assert "QĐ-UBND" not in out
    assert "QĐ-UBND" in tools.tra_cuu_tuan_thu(conn, "áp dụng trên địa bàn tỉnh", tinh="Đồng Nai")
    with pytest.raises(ValueError):
        tools.tim_van_ban(conn, "quy dinh mau", pham_vi="sai")


def test_noi_quan_he_so_dia_phuong_trung_theo_tinh(tmp_path):
    c = connect(tmp_path / "q.db")
    ids = {}
    for tinh in ("Đồng Nai", "Hồ Chí Minh"):
        ids[tinh] = upsert_document(
            c,
            {"so_ky_hieu": "28/2025/NQ-HĐND", "co_quan_ban_hanh": f"HĐND {tinh}", "tinh_hien_nay": tinh},
            parse_text("Điều 1. Bảng giá đất."),
        )
    src = upsert_document(
        c,
        {"so_ky_hieu": "30/2026/NQ-HĐND", "co_quan_ban_hanh": "HĐND Thành phố Đồng Nai", "tinh_hien_nay": "Đồng Nai"},
        parse_text("Điều 1. Sửa đổi."),
    )
    add_relation(c, src, "sua_doi", "28/2025/NQ-HĐND")
    assert c.execute("SELECT dst_doc_id FROM relations").fetchone()[0] == ids["Đồng Nai"]
    # Văn bản trung ương nhắc số trùng: không tự chọn.
    tw = upsert_document(c, {"so_ky_hieu": "1/2099/NĐ-CP", "co_quan_ban_hanh": "Chính phủ"}, parse_text("Điều 1. X."))
    add_relation(c, tw, "can_cu", "28/2025/NQ-HĐND")
    assert c.execute("SELECT dst_doc_id FROM relations WHERE src_doc_id = ?", (tw,)).fetchone()[0] is None


def test_xoa_van_ban(conn):
    from phapluat.store import delete_document, find_documents

    rows = find_documents(conn, "01/2099/QĐ-UBND", "Đồng Nai")
    assert len(rows) == 1
    delete_document(conn, rows[0]["id"], "bảng giá đất cũ")
    assert len(find_documents(conn, "01/2099/QĐ-UBND")) == 1
    assert "Đồng Nai" not in tools.tim_van_ban(conn, "quy dinh mau", pham_vi="tat_ca", bao_gom_het_hieu_luc=True)
    assert conn.execute("SELECT count(*) FROM changelog WHERE su_kien = 'xoa'").fetchone()[0] == 1
