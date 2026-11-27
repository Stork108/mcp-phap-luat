"""Kiểm thử bộ thu thập vbpl.vn trên trang mẫu đã lưu (không cần mạng)."""

import io
import json
from datetime import date
from pathlib import Path

import pytest

from phapluat import thuthap_vbpl as tt
from phapluat import tools
from phapluat.db import connect
from phapluat.parser import parse_text

FIX = Path(__file__).parent / "fixtures"
BLLD = FIX / "vbpl_bo_luat_lao_dong.html"
GDDH = FIX / "vbpl_luat_giao_duc_dai_hoc.html"
URL_BLLD = "https://vbpl.vn/van-ban/chi-tiet/bo-luat-lao-dong-so-45-2019-qh14--139264"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, url: str, status: int = 200):
        super().__init__(body)
        self.status = status
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWeb:
    """Giả lập vbpl.vn: ghi lại mọi url được gọi."""

    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        assert req.headers.get("User-agent") == tt.USER_AGENT
        if url not in self.pages:
            import urllib.error

            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return _Resp(self.pages[url], url)


ROBOTS = b"User-Agent: *\nAllow: /\nDisallow: /api/\nDisallow: /Pages/\n"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(tt.time, "sleep", lambda s: slept.append(s))
    return slept


def test_thuoc_tinh_bo_luat_lao_dong():
    kq = tt.doc_trang(_read(BLLD), URL_BLLD, hom_nay=date(2026, 11, 26))
    m = kq.meta
    assert m["so_ky_hieu"] == "45/2019/QH14"
    assert m["loai_van_ban"] == "Bộ luật"
    assert m["co_quan_ban_hanh"] == "Quốc hội"
    assert m["trich_yeu"] == "Bộ luật Lao động"
    assert m["ngay_ban_hanh"] == "2019-11-20"
    assert m["ngay_hieu_luc"] == "2021-01-01"
    assert "ngay_het_hieu_luc" not in m
    assert m["tinh_trang_nguon"] == "Hết hiệu lực một phần"
    assert m["ngay_kiem_tra"] == "2026-11-26"
    assert m["nguon"] == "vbpl.vn" and m["url_goc"] == URL_BLLD
    assert kq.canh_bao == []


def test_toan_van_giu_nguyen_van():
    kq = tt.doc_trang(_read(BLLD), URL_BLLD)
    p = parse_text(kq.chu)
    dieu = [u for u in p.walk() if u.loai == "dieu"]
    assert [d.so for d in dieu] == ["1", "2", "3"]
    assert dieu[0].tieu_de == "Phạm vi điều chỉnh"
    assert dieu[0].duong_dan() == "Chương I > Điều 1"
    # Chữ trong văn bản không bị đổi, các mảnh trong cùng một đoạn được nối liền.
    assert "Quốc hội ban hành Bộ luật Lao động." in kq.chu
    assert p.units[-1].loai == "ket"


def test_dieu_tach_hai_khoi_duoc_gop_lai():
    kq = tt.doc_trang(_read(GDDH), "https://vbpl.vn/van-ban/chi-tiet/x--2a8c2a10")
    assert kq.meta["so_ky_hieu"] == "125/2025/QH15"
    assert kq.meta["tinh_trang_nguon"] == "Còn hiệu lực"
    assert kq.meta["linh_vuc"] == "Giáo dục"
    assert kq.meta["trich_yeu"] == "Luật Giáo dục đại học"
    assert "Điều 1. Phạm vi điều chỉnh" in kq.chu.split("\n")
    dieu = [u for u in parse_text(kq.chu).walk() if u.loai == "dieu"]
    assert [(d.so, d.tieu_de) for d in dieu] == [("1", "Phạm vi điều chỉnh"), ("2", "Đối tượng áp dụng")]
    k = dieu[1].children
    assert [x.so for x in k] == ["1", "2"]
    assert k[0].noi_dung.startswith("1. Luật này áp dụng đối với cơ sở giáo dục đại học")


def test_van_ban_dia_phuong():
    kq = tt.doc_trang(_read(FIX / "vbpl_nghi_quyet_hdnd_bac_giang.html"), "https://vbpl.vn/van-ban/chi-tiet/x--164289")
    m = kq.meta
    assert m["so_ky_hieu"] == "70/2023/NQ-HĐND"
    assert m["co_quan_ban_hanh"] == "HĐND tỉnh Bắc Giang"
    assert m["tinh_ban_hanh_goc"] == "Bắc Giang"
    # Tỉnh hiện nay lấy đúng trường organization của vbpl.vn (Bắc Giang nay thuộc Bắc Ninh), không tự suy.
    assert m["tinh_hien_nay"] == "Bắc Ninh"
    assert m["ngay_het_hieu_luc"] == "2026-12-01"
    assert m["trich_yeu"].endswith("đối với nước thải trên địa bàn tỉnh Bắc Giang")
    assert any("Văn bản địa phương" in c for c in kq.canh_bao)


def _trang_tu_doc(doc: dict, content: str) -> str:
    b = content.encode("utf-8")
    flight = "1d:" + json.dumps(["$", "div", None, {"initialDoc": doc}], ensure_ascii=False) + "\n"
    flight += "2b:T" + format(len(b), "x") + "," + content
    return "<html><body><script>self.__next_f.push(" + json.dumps([1, flight], ensure_ascii=False) + ")</script></body></html>"


def _doc_mau(**kw) -> dict:
    doc = {
        "docNum": "99/2099/NĐ-CP",
        "docType": {"name": "Nghị định"},
        "title": "Nghị định số 99/2099/NĐ-CP quy định mẫu",
        "agencyName": "Chính phủ",
        "issueDate": "2099-01-02T00:00:00",
        "effFrom": "2099-02-01T00:00:00",
        "effTo": None,
        "effStatus": {"code": "TNHL", "name": "Tạm ngưng hiệu lực"},
        "documentContent": {"content": "$2b"},
        "documentRelatedList": [{"fileName": "1_body_content.html"}, {"fileName": "PL.pdf", "fileTitle": "Phụ lục I"}],
    }
    doc.update(kw)
    return doc


def test_canh_bao_phu_luc_va_tinh_trang_la():
    body = "<p>Số: 99/2099/NĐ-CP</p><p>Điều 1. Mẫu</p><p>Ban hành Danh mục tại Phụ lục I kèm theo Nghị định này.</p>"
    body += "<p>" + "Nội dung mẫu. " * 30 + "</p>"
    kq = tt.doc_trang(_trang_tu_doc(_doc_mau(), body), "https://vbpl.vn/van-ban/chi-tiet/x--1")
    assert kq.meta["thieu_phu_luc"] == 1
    assert "tinh_trang_nguon" not in kq.meta  # 'Tạm ngưng' không tự quy đổi
    text = " ".join(kq.canh_bao)
    assert "Tạm ngưng hiệu lực" in text
    assert "phụ lục kèm theo" in text
    assert "Phụ lục I" in text
    assert kq.meta["trich_yeu"] == "Quy định mẫu"


def test_trang_khong_co_toan_van():
    with pytest.raises(tt.LoiThuThap, match="không có toàn văn"):
        tt.doc_trang(_trang_tu_doc(_doc_mau(), ""), "https://vbpl.vn/van-ban/chi-tiet/x--1")


def test_trang_khong_co_du_lieu():
    with pytest.raises(tt.LoiThuThap, match="Không tìm thấy thuộc tính"):
        tt.doc_trang("<html><body>Không có gì</body></html>", "https://vbpl.vn/van-ban/chi-tiet/x--1")


def test_khong_bao_gio_goi_api_va_pages():
    web = _FakeWeb({"https://vbpl.vn/robots.txt": ROBOTS})
    bt = tt.BoTai(mo_url=web)
    for u in ("https://vbpl.vn/api/van-ban/1", "https://vbpl.vn/Pages/x.aspx", "https://example.com/van-ban/chi-tiet/a--1"):
        with pytest.raises(tt.LoiThuThap):
            bt.tai(u)
    assert all("/api/" not in c and "/Pages/" not in c for c in web.calls)


def test_gian_cach_toi_thieu_4_giay(_no_sleep):
    web = _FakeWeb({"https://vbpl.vn/robots.txt": ROBOTS, "https://vbpl.vn/a": b"1", "https://vbpl.vn/b": b"2"})
    bt = tt.BoTai(do_tre=0.5, mo_url=web)
    assert bt.do_tre == 4.0
    bt.tai("https://vbpl.vn/a")
    bt.tai("https://vbpl.vn/b")
    assert len(_no_sleep) == 2 and all(s > 3.9 for s in _no_sleep)


def test_gioi_han_so_lan_tai():
    web = _FakeWeb({"https://vbpl.vn/robots.txt": ROBOTS, "https://vbpl.vn/a": b"1"})
    bt = tt.BoTai(toi_da=2, mo_url=web)
    bt.tai("https://vbpl.vn/a")  # robots + a
    with pytest.raises(tt.LoiThuThap, match="tải đủ"):
        bt.tai("https://vbpl.vn/a")


def test_chuan_hoa_url():
    assert tt.chuan_hoa_url("https://vbpl.vn/en/van-ban/chi-tiet/abc--12") == "https://vbpl.vn/van-ban/chi-tiet/abc--12"
    with pytest.raises(tt.LoiThuThap):
        tt.chuan_hoa_url("https://vbpl.vn/van-ban/trung-uong")


def test_tim_theo_so_ky_hieu_trong_sitemap(tmp_path):
    urls = [
        "https://vbpl.vn/van-ban/chi-tiet/luat-dat-dai-so-31-2024-qh15--177815",
        "https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-131-2024-nd-cp-quy-dinh--1",
        "https://vbpl.vn/van-ban/chi-tiet/quyet-dinh-so-01-2024-qd-ubnd-tinh-a--2",
        "https://vbpl.vn/van-ban/chi-tiet/quyet-dinh-so-01-2024-qd-ubnd-tinh-b--3",
        "https://vbpl.vn/van-ban/chi-tiet/van-ban-hop-nhat-so-03-vbhn-btc-hop-nhat-nghi-dinh-so-131-2024-nd-cp--4",
        "https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-9-2025-nd-cp-sua-doi-nghi-dinh-so-131-2024-nd-cp--5",
        "https://vbpl.vn/van-ban/chi-tiet/luat-so-huu-tri-tue-so-50-2005-qh11--16748",
    ]
    assert tt.tim_trong_ds_url(urls, "50/2005/QH11") == urls[-1:]
    sua = "https://vbpl.vn/van-ban/chi-tiet/luat-sua-doi-luat-dat-dai-so-31-2024-qh15-luat-nha-o-so-27-2023-qh15-so-43-2024-qh15--170509"
    vbhn = "https://vbpl.vn/van-ban/chi-tiet/van-ban-hop-nhat-so-67-vbhn-vpqh-luat-doanh-nghiep--9"
    assert tt.tim_trong_ds_url(urls + [sua], "31/2024/QH15") == urls[:1]
    assert tt.tim_trong_ds_url([sua], "43/2024/QH15") == [sua]
    assert tt.tim_trong_ds_url([sua], "27/2023/QH15") == []
    assert tt.tim_trong_ds_url([vbhn], "67/VBHN-VPQH") == [vbhn]
    tt20 = "https://vbpl.vn/van-ban/chi-tiet/thong-tu-20-2026-tt-btc-huong-dan-nghi-dinh-so-320-2025-nd-cp--7"
    assert tt.tim_trong_ds_url([tt20], "20/2026/TT-BTC") == [tt20]
    assert tt.tim_trong_ds_url([tt20], "320/2025/NĐ-CP") == []
    hn = "https://vbpl.vn/van-ban/chi-tiet/van-ban-hop-nhat-ve-hoat-dong-dau-tu-so-142-2026-vbhn-lq-vpqh--8"
    assert tt.tim_trong_ds_url([hn, hn], "142/2026/VBHN-LQ-VPQH") == [hn]
    assert tt.manh_so_ky_hieu("131/2024/NĐ-CP") == "so-131-2024-nd-cp"
    assert tt.tim_trong_ds_url(urls, "31/2024/QH15") == urls[:1]
    assert tt.tim_trong_ds_url(urls, "1/2024/NĐ-CP") == []  # không khớp nhầm 131/2024
    assert len(tt.tim_trong_ds_url(urls, "01/2024/QĐ-UBND")) == 2

    sm = "<sitemapindex><sitemap><loc>https://vbpl.vn/sitemap/1.xml</loc></sitemap></sitemapindex>"
    us = "<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>"
    web = _FakeWeb(
        {
            "https://vbpl.vn/robots.txt": ROBOTS,
            "https://vbpl.vn/sitemap.xml": sm.encode(),
            "https://vbpl.vn/sitemap/1.xml": us.encode(),
        }
    )
    cm = tt.ChiMucSitemap(tmp_path, tt.BoTai(mo_url=web))
    assert cm.tim("31/2024/QH15", in_tien_do=lambda s: None) == urls[:1]
    n = len(web.calls)
    assert cm.tim("131/2024/NĐ-CP", in_tien_do=lambda s: None) == urls[1:2]
    assert len(web.calls) == n  # lần sau đọc từ bản lưu trên máy


def test_thu_thap_url_ghi_vao_kho(tmp_path):
    web = _FakeWeb({"https://vbpl.vn/robots.txt": ROBOTS, URL_BLLD: BLLD.read_bytes()})
    conn = connect(tmp_path / "t.db")
    doc_id, kq = tt.thu_thap_url(conn, URL_BLLD, tt.BoTai(mo_url=web), luu_html=tmp_path / "html")
    assert kq.so_dieu == 3
    assert (tmp_path / "html" / "139264.html").exists()
    assert web.calls == ["https://vbpl.vn/robots.txt", URL_BLLD]
    out = tools.trich_dieu_khoan(conn, "45/2019/QH14", "1")
    assert "Bộ luật Lao động quy định tiêu chuẩn lao động" in out
    assert "vbpl.vn" in out and URL_BLLD in out
    with pytest.raises(tt.LoiThuThap, match="không nhập"):
        tt.thu_thap_url(conn, URL_BLLD, tt.BoTai(mo_url=web), so_mong_doi="10/2012/QH13")
    # Thu thập lại cùng văn bản thì cập nhật, không tạo bản trùng.
    tt.thu_thap_url(conn, URL_BLLD, tt.BoTai(mo_url=web))
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


def test_tinh_hien_nay_chi_lay_tu_organization():
    doc = _doc_mau(
        docNum="493/QĐ-UBND",
        docType={"name": "Quyết định"},
        title="Quyết định số 493/QĐ-UBND mẫu",
        agencyName="UBND Thành phố Đồng Nai",
        effStatus={"code": "CHL", "name": "Còn hiệu lực"},
        documentRelatedList=[],
        organization={"name": "Đồng Nai", "code": "H75", "orgType": "1"},
    )
    noi_dung = "<p>QUYẾT ĐỊNH số 493/QĐ-UBND</p>" + "<p>Điều 1. Nội dung mẫu đủ dài để nhập.</p>" * 10
    m = tt.doc_trang(_trang_tu_doc(doc, noi_dung), "https://vbpl.vn/van-ban/chi-tiet/x--1").meta
    assert m["tinh_ban_hanh_goc"] == "Đồng Nai" and m["tinh_hien_nay"] == "Đồng Nai"
    doc["organization"] = {"name": "Hồ Chí Minh", "code": "H79", "orgType": "0"}
    m = tt.doc_trang(_trang_tu_doc(doc, noi_dung), "https://vbpl.vn/van-ban/chi-tiet/x--1").meta
    assert "tinh_hien_nay" not in m  # orgType 0 là cơ quan trung ương: không gán tỉnh


def test_bo_qua_van_ban_het_hieu_luc(tmp_path):
    url = "https://vbpl.vn/van-ban/chi-tiet/x--2"
    doc = _doc_mau(effStatus={"code": "HHL", "name": "Hết hiệu lực toàn bộ"}, effTo="2099-06-01T00:00:00")
    noi_dung = "<p>NGHỊ ĐỊNH số 99/2099/NĐ-CP</p>" + "<p>Điều 1. Nội dung mẫu đủ dài để nhập.</p>" * 10
    web = _FakeWeb({"https://vbpl.vn/robots.txt": ROBOTS, url: _trang_tu_doc(doc, noi_dung).encode("utf-8")})
    conn = connect(tmp_path / "t.db")
    with pytest.raises(tt.BoQuaHetHieuLuc, match="hết hiệu lực toàn bộ từ 2099-06-01"):
        tt.thu_thap_url(conn, url, tt.BoTai(mo_url=web), bo_qua_het_hieu_luc=True)
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
    # Không bật bỏ qua thì vẫn nhập như trước (để giữ bản liền trước khi cần).
    tt.thu_thap_url(conn, url, tt.BoTai(mo_url=web))
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
