from pathlib import Path

from phapluat.parser import parse_text

FIX = Path(__file__).parent / "fixtures" / "mau_nghi_dinh.txt"


def _units():
    return parse_text(FIX.read_text(encoding="utf-8"))


def test_header():
    h = _units().header
    assert h["so_ky_hieu"] == "999/2099/NĐ-CP"
    assert h["ngay_ban_hanh"] == "2099-03-15"
    assert h["ngay_hieu_luc"] == "2099-05-01"
    assert h["co_quan_ban_hanh"] == "CHÍNH PHỦ"
    assert h["loai_van_ban"] == "Nghị định"
    assert h["trich_yeu"] == "Quy định mẫu dùng để kiểm thử bộ tách cấu trúc"


def test_structure():
    p = _units()
    dieu = [u for u in p.walk() if u.loai == "dieu"]
    assert [d.so for d in dieu] == ["1", "2", "3", "4"]  # Điều 1 trong phụ lục không bị tính
    d2 = dieu[1]
    assert [k.so for k in d2.children] == ["1", "2", "2a", "3"]
    k3 = d2.children[3]
    assert [d.so for d in k3.children] == ["a", "b", "c"]
    # dòng 'đ)' sai thứ tự vẫn nằm nguyên văn trong điểm b
    assert "đ) Dòng này không đúng thứ tự" in k3.children[1].noi_dung
    d3 = dieu[2]
    assert [k.so for k in d3.children] == ["1", "2"]
    assert "Năm 2099." in d3.children[1].noi_dung
    assert d3.duong_dan() == "Chương II > Mục 1 > Điều 3"


def test_titles_and_toplevel():
    p = _units()
    loai = [u.loai for u in p.units]
    assert loai == ["mo_dau", "chuong", "chuong", "ket", "phu_luc"]
    assert p.units[1].tieu_de == "QUY ĐỊNH CHUNG"
    assert p.units[2].children[0].tieu_de == "TRỢ CẤP THÔI VIỆC"


def test_verbatim_roundtrip():
    """Ghép các đơn vị cấp cao nhất phải ra đúng nguyên văn (bỏ dòng trống đầu/cuối)."""
    p = _units()
    original = FIX.read_text(encoding="utf-8").strip("\n")
    rebuilt = "\n".join(u.noi_dung for u in p.units)
    norm = lambda s: [l for l in s.split("\n") if l.strip()]  # noqa: E731
    assert norm(rebuilt) == norm(original)
