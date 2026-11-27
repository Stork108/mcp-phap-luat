"""Kiểm thử đọc quan hệ từ nội dung văn bản. Văn bản mẫu hư cấu (năm 2099)."""

from pathlib import Path

import pytest

from phapluat import tools
from phapluat.cli import main, nhap_tep
from phapluat.db import connect
from phapluat.parser import parse_text
from phapluat.quanhe import TU_DOC, _vi_tri_trong, doc_hieu_luc, doc_sua_doi, ghi_quan_he, tach_so
from phapluat.store import add_relation, upsert_document

FIX = Path(__file__).parent / "fixtures" / "mau_nghi_dinh.txt"

SUA_DOI = """CHÍNH PHỦ
Số: 1001/2099/NĐ-CP

NGHỊ ĐỊNH
Sửa đổi, bổ sung một số điều của Nghị định số 999/2099/NĐ-CP

Căn cứ Luật Mẫu số 1/2098/QH99;

Điều 1. Sửa đổi, bổ sung một số điều của Nghị định số 999/2099/NĐ-CP ngày 15 tháng 3 năm 2099 của Chính phủ
1. Sửa đổi, bổ sung khoản 1 Điều 3 như sau:
“1. Nội dung mới của khoản 1, dẫn chiếu khoản 9 Điều 50.
2. Dòng trong ngoặc kép không phải lệnh sửa đổi.”
2. Bổ sung điểm c, điểm d vào khoản 2; sửa đổi khoản 5 Điều 2 như sau:
a) Bổ sung điểm c, điểm d vào khoản 2 như sau:
“c) Mới;
d) Mới.”
b) Sửa đổi khoản 5 như sau:
“5. Mới.”
3. Thay cụm từ “lao động mẫu” bằng cụm từ “lao động thử” tại khoản 2 Điều 1.
4. Bãi bỏ Điều 4.

Điều 2. Hiệu lực thi hành
1. Nghị định này có hiệu lực thi hành từ ngày 01 tháng 7 năm 2099.
2. Kể từ ngày Nghị định này có hiệu lực thi hành, các văn bản sau đây hết hiệu lực thi hành:
a) Nghị định số 997/2099/NĐ-CP ngày 01 tháng 01 năm 2099 của Chính phủ quy định mẫu;
b) Điều 2 Nghị định số 996/2099/NĐ-CP ngày 01 tháng 01 năm 2099 sửa đổi Nghị định số 999/2099/NĐ-CP.
3. Nghị định này thay thế Nghị định số 995/2099/NĐ-CP.
4. Hồ sơ đã nộp trước ngày Nghị định này có hiệu lực tiếp tục thực hiện theo Nghị định số 994/2099/NĐ-CP.
"""


def test_tach_so():
    assert tach_so("Căn cứ Luật số 63/2025/QH15; Pháp lệnh 01/2012/UBTVQH13; 142/2026/VBHN-LQ-VPQH; ngày 1/7/2025") == [
        "63/2025/QH15",
        "01/2012/UBTVQH13",
        "142/2026/VBHN-LQ-VPQH",
    ]


def test_vi_tri_gan_diem_voi_khoan_dung():
    assert _vi_tri_trong("Bổ sung điểm c, điểm d vào khoản 2; sửa đổi khoản 5, khoản 11 Điều 3") == [
        "điểm c khoản 2 Điều 3",
        "điểm d khoản 2 Điều 3",
        "khoản 5 Điều 3",
        "khoản 11 Điều 3",
    ]
    assert _vi_tri_trong("Bổ sung khoản 4", "7") == ["khoản 4 Điều 7"]


def test_doc_sua_doi_bo_qua_ngoac_kep():
    dieu = SUA_DOI.split("Điều 1. ", 1)[1].split("\n\nĐiều 2.")[0]
    qs = doc_sua_doi("1", "Điều 1. " + dieu, None)
    vt = {(q.loai, q.dst_so, q.dst_vi_tri) for q in qs}
    assert ("sua_doi", "999/2099/NĐ-CP", "khoản 1 Điều 3") in vt
    assert ("sua_doi", "999/2099/NĐ-CP", "điểm c khoản 2 Điều 2") in vt
    assert ("sua_doi", "999/2099/NĐ-CP", "khoản 5 Điều 2") in vt
    assert ("sua_doi", "999/2099/NĐ-CP", "khoản 2 Điều 1") in vt
    assert ("bai_bo", "999/2099/NĐ-CP", "Điều 4") in vt
    assert not any("Điều 50" in (q.dst_vi_tri or "") for q in qs)


def test_doc_hieu_luc():
    dieu = "Điều 2. " + SUA_DOI.split("Điều 2. ", 1)[1]
    vt = {(q.loai, q.dst_so, q.dst_vi_tri) for q in doc_hieu_luc("2", dieu)}
    assert vt == {
        ("het_hieu_luc", "997/2099/NĐ-CP", None),
        ("het_hieu_luc", "996/2099/NĐ-CP", "Điều 2"),
        ("thay_the", "995/2099/NĐ-CP", None),
    }


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    nhap_tep(c, str(FIX), {"tinh_trang_nguon": "Còn hiệu lực", "nguon": "kiem-thu"})
    upsert_document(
        c,
        {
            "so_ky_hieu": "1001/2099/NĐ-CP",
            "co_quan_ban_hanh": "Chính phủ",
            "loai_van_ban": "Nghị định",
            "trich_yeu": "Sửa đổi, bổ sung một số điều của Nghị định số 999/2099/NĐ-CP",
            "tinh_trang_nguon": "Còn hiệu lực",
        },
        parse_text(SUA_DOI),
    )
    yield c
    c.close()


def test_ghi_quan_he_va_canh_bao_khi_trich(conn):
    ghi_quan_he(conn)
    out = tools.trich_dieu_khoan(conn, "999/2099/NĐ-CP", "3", khoan="1")
    assert "CẢNH BÁO" in out and "1001/2099/NĐ-CP" in out and "tự đọc" in out
    rel = tools.van_ban_lien_quan(conn, "1001/2099/NĐ-CP")
    assert "căn cứ 1/2098/QH99" in rel
    assert "làm hết hiệu lực 997/2099/NĐ-CP" in rel


def test_chay_lai_khong_nhan_doi_va_giu_quan_he_ghi_tay(conn):
    src = conn.execute("SELECT id FROM documents WHERE so_ky_hieu = '1001/2099/NĐ-CP'").fetchone()["id"]
    add_relation(conn, src, "huong_dan", "1/2098/QH99", None, None, None, "ghi tay")
    n1 = len(ghi_quan_he(conn)[src])
    ghi_quan_he(conn)
    tu_doc = conn.execute(
        "SELECT count(*) FROM relations WHERE src_doc_id = ? AND ghi_chu LIKE ?", (src, f"%{TU_DOC}%")
    ).fetchone()[0]
    assert tu_doc == n1
    assert conn.execute("SELECT count(*) FROM relations WHERE ghi_chu = 'ghi tay'").fetchone()[0] == 1


def test_lenh_doc_quan_he(tmp_path, capsys):
    db = tmp_path / "k.db"
    c = connect(db)
    upsert_document(
        c,
        {"so_ky_hieu": "1001/2099/NĐ-CP", "co_quan_ban_hanh": "Chính phủ", "trich_yeu": "Sửa đổi mẫu"},
        parse_text(SUA_DOI),
    )
    c.close()
    assert main(["--db", str(db), "doc-quan-he", "--chi-tiet"]) == 0
    out = capsys.readouterr().out
    assert "het_hieu_luc 997/2099/NĐ-CP" in out and "cần đối chiếu" in out


def test_khong_nham_quy_dinh_chuyen_tiep_cum_tu_mau_bieu():
    dieu = """Điều 24. Quy định chuyển tiếp và hiệu lực thi hành
1. Thông tư này có hiệu lực từ ngày 01 tháng 7 năm 2099.
2. Kể từ thời điểm tổ chức sử dụng hóa đơn theo quy định tại Nghị định số 990/2099/NĐ-CP, nếu phát hiện hóa đơn sai thì lập hóa đơn thay thế.
3. Thay thế cụm từ "doanh nghiệp nhà nước" bằng cụm từ "doanh nghiệp mẫu" tại khoản 1 Điều 35 của Luật Mẫu số 83/2098/QH99.
- Cụm từ "Điều 60 Nghị định này" bằng cụm từ "Phụ lục I Nghị định số 989/2099/NĐ-CP" tại điểm b khoản 2 Điều 94.
4. Thông tư này thay thế mẫu số 01/TKN-CNKD kèm theo Thông tư số 50/2099/TT-BTC.
5. Bãi bỏ Thông tư số 49/2099/TT-BTC."""
    vt = {(q.loai, q.dst_so, q.dst_vi_tri) for q in doc_hieu_luc("24", dieu)}
    assert vt == {("bai_bo", "49/2099/TT-BTC", None)}


def test_so_ky_hieu_co_dau_cach_va_mau_bieu():
    from phapluat.quanhe import chuan_hoa_chu

    assert tach_so(chuan_hoa_chu("Luật Dược số 105/ 2016/QH13")) == ["105/2016/QH13"]
    assert tach_so("Bổ sung Mẫu số 01/BK-ĐCTT, Mẫu số 01/TH-DT vào Phụ lục IA") == []
    assert tach_so("văn bản số 716/UBTVQH13-CVĐXH") == []
    assert tach_so("hợp nhất số 18/VBHN-VPQH") == ["18/VBHN-VPQH"]
