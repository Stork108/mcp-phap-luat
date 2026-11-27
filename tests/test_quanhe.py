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
    assert vt == {("bai_bo", "49/2099/TT-BTC", None), ("sua_doi", "50/2099/TT-BTC", "mẫu số 01/TKN-CNKD")}


def test_so_ky_hieu_co_dau_cach_va_mau_bieu():
    from phapluat.quanhe import chuan_hoa_chu

    assert tach_so(chuan_hoa_chu("Luật Dược số 105/ 2016/QH13")) == ["105/2016/QH13"]
    assert tach_so("Bổ sung Mẫu số 01/BK-ĐCTT, Mẫu số 01/TH-DT vào Phụ lục IA") == []
    assert tach_so("văn bản số 716/UBTVQH13-CVĐXH") == []
    assert tach_so("hợp nhất số 18/VBHN-VPQH") == ["18/VBHN-VPQH"]


def test_danh_sach_bai_bo_nhieu_van_ban_va_mo_ta():
    dieu = """Điều 38. Hiệu lực thi hành
1. Nghị định này có hiệu lực từ ngày 01 tháng 7 năm 2099. Khoản 9 Điều 60 của Luật này có hiệu lực thi hành từ ngày Nghị quyết số 61/2098/QH99 hết hiệu lực.
2. Nghị định số 163/2098/NĐ-CP ngày 29 tháng 12 năm 2098 của Chính phủ về giao dịch bảo đảm, Nghị định số 11/2099/NĐ-CP ngày 22 tháng 02 năm 2099 của Chính phủ sửa đổi Nghị định số 163/2098/NĐ-CP và Nghị định số 15/2099/NĐ-CP hết hiệu lực kể từ ngày Nghị định này có hiệu lực thi hành.
3. Bãi bỏ quy định tại:
a) Điều 2 Nghị định số 91/2098/NĐ-CP ngày 01 tháng 10 năm 2098;
b) Điều 3 Nghị định số 12/2099/NĐ-CP.
4. Các khoản 1, 3 Điều 7 và khoản 2 Điều 8 của Nghị định số 135/2098/NĐ-CP hết hiệu lực.
5. Bãi bỏ quy định về ưu đãi tại Điều 6 Nghị định số 69/2098/NĐ-CP."""
    vt = {(q.loai, q.dst_so, q.dst_vi_tri) for q in doc_hieu_luc("38", dieu)}
    assert vt == {
        ("het_hieu_luc", "163/2098/NĐ-CP", None),
        ("het_hieu_luc", "11/2099/NĐ-CP", None),
        ("bai_bo", "91/2098/NĐ-CP", "Điều 2"),
        ("bai_bo", "12/2099/NĐ-CP", "Điều 3"),
        ("het_hieu_luc", "135/2098/NĐ-CP", "khoản 1 Điều 7"),
        ("het_hieu_luc", "135/2098/NĐ-CP", "khoản 3 Điều 7"),
        ("het_hieu_luc", "135/2098/NĐ-CP", "khoản 2 Điều 8"),
        ("bai_bo", "69/2098/NĐ-CP", "Điều 6"),
    }


def test_thay_cum_tu_ghi_sua_doi_vi_tri_ngoai_ngoac_kep():
    dieu = """Điều 217. Sửa đổi, bổ sung một số điều của luật có liên quan
3. Thay thế cụm từ "doanh nghiệp nhà nước" bằng cụm từ "doanh nghiệp mẫu" quy định tại điểm m khoản 1 Điều 35 và điểm k khoản 1 Điều 37 của Luật Ngân sách nhà nước số 83/2098/QH99; khoản 2 Điều 4 của Luật Quản lý thử số 08/2099/QH99.
4. Thay thế, bãi bỏ các điểm, khoản, cụm từ tại Nghị định số 71/2098/NĐ-CP như sau:
- Cụm từ "khoản 4 Điều 68 Nghị định số 102/2098/NĐ-CP" bằng cụm từ "Điều 5" tại điểm b khoản 2 Điều 94."""
    vt = {(q.loai, q.dst_so, q.dst_vi_tri) for q in doc_sua_doi("217", dieu, None)}
    assert ("sua_doi", "83/2098/QH99", "điểm m khoản 1 Điều 35") in vt
    assert ("sua_doi", "83/2098/QH99", "điểm k khoản 1 Điều 37") in vt
    assert ("sua_doi", "08/2099/QH99", "khoản 2 Điều 4") in vt
    assert ("sua_doi", "71/2098/NĐ-CP", "điểm b khoản 2 Điều 94") in vt
    assert not any(q[1] == "102/2098/NĐ-CP" for q in vt)


def test_van_ban_trong_ten_van_ban_khac_khong_bi_tinh():
    dieu = """Điều 25. Hiệu lực thi hành
2. Kể từ ngày Thông tư này có hiệu lực thi hành, Thông tư số 32/2098/TT-BTC ngày 31 tháng 5 năm 2098 hướng dẫn thực hiện một số điều của Luật Quản lý thuế, Nghị định số 123/2098/NĐ-CP (được sửa đổi tại Nghị định số 70/2098/NĐ-CP) hết hiệu lực.
3. Luật doanh nghiệp số 60/2097/QH99 và Luật sửa đổi, bổ sung Điều 170 của Luật doanh nghiệp số 37/2098/QH99 hết hiệu lực kể từ ngày Luật này có hiệu lực.
4. Nghị định số 196/CP ngày 31 tháng 12 năm 2094; Nghị định số 93/2097/NĐ-CP ngày 11 tháng 11 năm 2097; Nghị định số 33/2098/NĐ-CP hết hiệu lực.
5. Các văn bản sau đây hết hiệu lực:
d) Nghị định số 57/2098/NĐ-CP bổ sung điểm g khoản 2 Điều 20 Nghị định số 218/2097/NĐ-CP;
đ) Chương 2 Thông tư số 09/2097/TT-BTC."""
    vt = {(q.loai, q.dst_so, q.dst_vi_tri) for q in doc_hieu_luc("25", dieu)}
    assert vt == {
        ("het_hieu_luc", "32/2098/TT-BTC", None),
        ("het_hieu_luc", "60/2097/QH99", None),
        ("het_hieu_luc", "37/2098/QH99", None),
        ("het_hieu_luc", "93/2097/NĐ-CP", None),
        ("het_hieu_luc", "33/2098/NĐ-CP", None),
        ("het_hieu_luc", "57/2098/NĐ-CP", None),
        ("het_hieu_luc", "09/2097/TT-BTC", "Chương 2"),
    }


def test_muc_con_ke_thua_dieu_khi_co_dong_danh_so_trong_trich_dan_khong_ngoac():
    dieu = """Điều 219. Sửa đổi, bổ sung một số điều của Bộ luật Tố tụng dân sự số 92/2098/QH99
2. Sửa đổi, bổ sung Điều 32 như sau:
a) Sửa đổi, bổ sung tên điều, khoản 1; bổ sung các khoản 1a, 1b và 1c vào sau khoản 1 như sau:
1. Dòng trích dẫn mất ngoặc kép.
b) Bãi bỏ điểm a.4 khoản 10 như sau:"""
    vt = {(q.loai, q.dst_vi_tri) for q in doc_sua_doi("219", dieu, None)}
    assert {("sua_doi", "khoản 1 Điều 32"), ("sua_doi", "khoản 1a Điều 32"), ("sua_doi", "khoản 1c Điều 32")} <= vt
    assert ("bai_bo", "điểm a.4 khoản 10 Điều 32") in vt


def test_vong_4_va_noi_van_ban_ngang_hang_vi_tri_muc_chuong():
    dieu = """Điều 99. Hiệu lực thi hành
3. Thông tư này bãi bỏ:
g) Thông tư số 19/2097/TT-BTC ngày 18 tháng 3 năm 2097 hướng dẫn giao dịch điện tử trong lĩnh vực thuế và Thông tư số 46/2098/TT-BTC ngày 09 tháng 7 năm 2098 sửa đổi, bổ sung một số điều của Thông tư số 19/2097/TT-BTC."""
    vt = {(q.loai, q.dst_so) for q in doc_hieu_luc("99", dieu)}
    assert vt == {("bai_bo", "19/2097/TT-BTC"), ("bai_bo", "46/2098/TT-BTC")}
    assert _vi_tri_trong("Sửa đổi, bổ sung tên Mục 2 Chương II") == ["Mục 2 Chương II"]
    assert _vi_tri_trong("Sửa đổi, bổ sung khoản 16 Mục I Phần IV") == ["khoản 16 Mục I Phần IV"]
    assert _vi_tri_trong("mục VII của Phụ lục III") == ["mục VII của Phụ lục III"]
