"""Thu thập văn bản từ trang chi tiết của vbpl.vn.

Kết quả khảo sát (11/2026): trang chi tiết có dạng
    https://vbpl.vn/van-ban/chi-tiet/<tên-không-dấu>--<mã>
và máy chủ trả về sẵn toàn văn cùng thuộc tính văn bản trong luồng dữ liệu
Next.js (các đoạn ``self.__next_f.push``). Công cụ chỉ đọc đúng trang đó,
không gọi /api/ hay /Pages/ (robots.txt cấm), không chạy JavaScript,
mỗi yêu cầu cách nhau ít nhất 4 giây.

Muốn tìm theo số ký hiệu, công cụ đọc sơ đồ trang (sitemap) của vbpl.vn,
lưu lại trên máy để lần sau không phải tải lại.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .parser import parse_text
from .status import CHUA_HIEU_LUC, CON_HIEU_LUC, HET_MOT_PHAN, HET_TOAN_BO, chuan_hoa_tinh_trang
from .textnorm import bo_dau, nfc

USER_AGENT = "mcp-phap-luat/0.1 (cong cu tra cuu ca nhan; thu thap cham)"
BASE = "https://vbpl.vn"
CAM = ("/api/", "/pages/")  # robots.txt: Disallow /api/ và /Pages/
DO_TRE_TOI_THIEU = 4.0
RE_CHI_TIET = re.compile(r"^/(?:en/)?van-ban/chi-tiet/([^/?#]+)$")

# Mã tình trạng hiệu lực của vbpl.vn -> tình trạng dùng trong kho.
MA_TINH_TRANG = {
    "CHL": CON_HIEU_LUC,
    "CCHL": CHUA_HIEU_LUC,
    "HHL": HET_TOAN_BO,
    "HHL1P": HET_MOT_PHAN,
    "HHL1P1": HET_MOT_PHAN,
    "HHL1P2": HET_MOT_PHAN,
    "HHL1P3": HET_MOT_PHAN,
    "HHL1P4": HET_MOT_PHAN,
}


class LoiThuThap(Exception):
    pass


# ---------------------------------------------------------------------------
# Tải trang lịch sự


class BoTai:
    """Tải trang vbpl.vn: tôn trọng robots.txt, không bao giờ gọi /api/ hay /Pages/, có giãn cách."""

    def __init__(self, do_tre: float = DO_TRE_TOI_THIEU, toi_da: int | None = None, mo_url=None):
        self.do_tre = max(do_tre, DO_TRE_TOI_THIEU)
        self.toi_da = toi_da
        self.so_lan = 0
        self._mo_url = mo_url or urllib.request.urlopen
        self._lan_cuoi = 0.0
        self._robots: urllib.robotparser.RobotFileParser | None = None

    def _cho(self) -> None:
        if self.toi_da is not None and self.so_lan >= self.toi_da:
            raise LoiThuThap(f"Đã tải đủ {self.toi_da} lần trong lần chạy này; dừng để không tải quá nhiều.")
        self.so_lan += 1
        con = self.do_tre - (time.monotonic() - self._lan_cuoi)
        if self._lan_cuoi and con > 0:
            time.sleep(con)
        self._lan_cuoi = time.monotonic()

    def _tai_tho(self, url: str, timeout: int = 60) -> tuple[int, str, bytes]:
        self._cho()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "vi"})
        try:
            with self._mo_url(req, timeout=timeout) as resp:
                return resp.status, resp.geturl(), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, url, b""

    def duoc_phep(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "vbpl.vn":
            return False
        if parts.path.lower().startswith(CAM):
            return False
        if self._robots is None:
            status, _, body = self._tai_tho(BASE + "/robots.txt")
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(body.decode("utf-8", "replace").splitlines() if status == 200 else [])
            self._robots = rp
        return self._robots.can_fetch(USER_AGENT, url)

    def tai(self, url: str) -> bytes:
        if not self.duoc_phep(url):
            raise LoiThuThap(f"Không tải {url}: ngoài vbpl.vn hoặc robots.txt không cho phép.")
        status, final, body = self._tai_tho(url)
        if status != 200:
            raise LoiThuThap(f"vbpl.vn trả về mã {status} cho {url}.")
        if urllib.parse.urlsplit(final).netloc != "vbpl.vn":
            raise LoiThuThap(f"Trang chuyển hướng ra ngoài vbpl.vn ({final}).")
        return body


# ---------------------------------------------------------------------------
# Đọc dữ liệu nhúng của Next.js


def doc_luong_rsc(html: str) -> dict[str, str]:
    """Ghép các đoạn self.__next_f.push([1, "..."]) rồi tách thành các dòng dữ liệu theo mã."""
    parts: list[str] = []
    for m in re.finditer(r"self\.__next_f\.push\((\[.*?\])\)\s*</script>", html, re.S):
        try:
            arr = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if len(arr) > 1 and arr[0] == 1 and isinstance(arr[1], str):
            parts.append(arr[1])
    data = "".join(parts).encode("utf-8")
    rows: dict[str, str] = {}
    i, n = 0, len(data)
    while i < n:
        m = re.match(rb"([0-9a-f]+):", data[i : i + 24])
        if not m:
            j = data.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        rid = m.group(1).decode()
        i += m.end()
        if data[i : i + 1] == b"T":  # dòng chữ: T<độ dài hệ 16>,<nội dung>
            c = data.index(b",", i)
            length = int(data[i + 1 : c], 16)
            rows[rid] = data[c + 1 : c + 1 + length].decode("utf-8")
            i = c + 1 + length
        else:
            j = data.find(b"\n", i)
            j = n if j < 0 else j
            rows[rid] = data[i:j].decode("utf-8")
            i = j + 1
    return rows


def tach_van_ban(html: str) -> tuple[dict, str]:
    """Trả về (thuộc tính văn bản 'initialDoc', HTML toàn văn)."""
    rows = doc_luong_rsc(html)
    doc = None
    for v in rows.values():
        m = re.search(r'"initialDoc"\s*:\s*', v)
        if m:
            try:
                doc, _ = json.JSONDecoder().raw_decode(v[m.end() :])
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict):
                break
            doc = None
    if not doc:
        raise LoiThuThap("Không tìm thấy thuộc tính văn bản trong trang (cấu trúc vbpl.vn có thể đã đổi).")
    content = ((doc.get("documentContent") or {}).get("content")) or ""
    if isinstance(content, str) and content.startswith("$"):
        content = rows.get(content[1:], "")
    return doc, content or ""


# ---------------------------------------------------------------------------
# HTML toàn văn -> chữ theo dòng (giữ nguyên chữ, chỉ bỏ thẻ)

_KHOI = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "table", "tbody", "thead",
    "tfoot", "tr", "td", "th", "section", "article", "header", "footer", "blockquote", "pre", "body",
    "center", "dd", "dt", "dl",
}
_BO = {"script", "style", "noscript", "head", "meta", "link", "title", "template", "svg"}


def html_sang_chu(content_html: str) -> str:
    from bs4 import BeautifulSoup, Comment, NavigableString, Tag

    soup = BeautifulSoup(content_html, "html.parser")
    lines: list[str] = []
    buf: list[str] = []

    def flush(target: list[str]) -> None:
        s = re.sub(r"[ \t \r\n]+", " ", "".join(buf)).strip()
        buf.clear()
        if s:
            target.append(s)

    def walk(node, target: list[str]) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                buf.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in _BO:
                continue
            if name == "br":
                flush(target)
                continue
            if name == "tr":
                flush(target)
                cells: list[list[str]] = []
                for cell in child.find_all(["td", "th"], recursive=False):
                    cell_lines: list[str] = []
                    walk(cell, cell_lines)
                    flush(cell_lines)
                    if cell_lines:
                        cells.append(cell_lines)
                if cells and all(len(c) == 1 for c in cells):
                    target.append(" | ".join(c[0] for c in cells))
                else:
                    for c in cells:
                        target.extend(c)
                continue
            if name in _KHOI:
                flush(target)
                walk(child, target)
                flush(target)
                continue
            walk(child, target)
            if "num-prefix" in (child.get("class") or []):
                buf.append(" ")

    walk(soup, lines)
    flush(lines)
    return nfc("\n".join(_gop_dong_dieu(lines)))


# ---------------------------------------------------------------------------
# Thuộc tính -> trường trong kho


def _ngay(v) -> str | None:
    if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
        return v[:10]
    return None


def _trich_yeu(title: str, loai: str | None, so: str | None) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    if not t:
        return t
    if t.isupper():
        t = t[0] + t[1:].lower()
    if so:
        t = re.sub(r"\s*số\s*:?\s*" + re.escape(so) + r"\b", " ", t, flags=re.I).strip()
        t = re.sub(r"\s+" + re.escape(so) + r"\b", " ", t, flags=re.I).strip()
    if loai and bo_dau(loai) not in ("luat", "bo luat") and bo_dau(t).startswith(bo_dau(loai) + " "):
        t = t[len(loai) :].strip()  # 'Nghị định quy định ...' -> 'Quy định ...'
        t = t[:1].upper() + t[1:]
    return re.sub(r"\s+", " ", t).strip(" ,.-")


_RE_KEM_THEO = re.compile(
    r"kèm theo (luật|bộ luật|nghị định|thông tư|quyết định|nghị quyết|pháp lệnh|chỉ thị|văn bản) này", re.I
)


def _nhac_phu_luc_kem_theo(chu: str) -> bool:
    """Có dòng nhắc 'phụ lục ... kèm theo <loại văn bản> này' (phụ lục là một phần của chính văn bản)."""
    return any("phụ lục" in line.lower() and _RE_KEM_THEO.search(line) for line in chu.split("\n"))


def _gop_dong_dieu(lines: list[str]) -> list[str]:
    """Gộp dòng 'Điều 5.' đứng riêng với dòng tên điều ngay sau (do trang tách hai khối)."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        if re.fullmatch(r"Điều \d+[a-zđ]?\.", lines[i]) and i + 1 < len(lines) and not lines[i + 1].startswith(
            ("Điều ", "1.", "Chương", "CHƯƠNG")
        ):
            out.append(lines[i] + " " + lines[i + 1])
            i += 2
        else:
            out.append(lines[i])
            i += 1
    return out


@dataclass
class KetQua:
    meta: dict
    chu: str
    canh_bao: list[str] = field(default_factory=list)
    so_dieu: int = 0


def chuyen_doi(doc: dict, content_html: str, url: str, hom_nay: date | None = None) -> KetQua:
    """Chuyển thuộc tính và toàn văn của vbpl.vn thành (meta, chữ) cho store.upsert_document."""
    canh_bao: list[str] = []
    so = (doc.get("docNum") or "").strip()
    loai = ((doc.get("docType") or {}).get("name") or "").strip() or None
    issues = doc.get("documentIssues") or []
    co_quan = (doc.get("agencyName") or "").strip()
    if not co_quan and issues:
        co_quan = ", ".join(dict.fromkeys(i.get("agencyName") for i in issues if i.get("agencyName")))
    eff = doc.get("effStatus") or {}
    tinh_trang = MA_TINH_TRANG.get(eff.get("code") or "") or chuan_hoa_tinh_trang(eff.get("name"))
    if eff.get("name") and not tinh_trang:
        canh_bao.append(f"vbpl.vn ghi tình trạng '{eff.get('name')}', chưa quy đổi được: cần kiểm tra.")
    linh_vuc = ", ".join(
        f["name"] for f in (doc.get("documentFields") or []) if f.get("name") and f["name"] != "Chưa phân loại"
    )
    meta = {
        "so_ky_hieu": so,
        "loai_van_ban": loai,
        "co_quan_ban_hanh": co_quan,
        "trich_yeu": _trich_yeu(doc.get("title") or "", loai, so),
        "ngay_ban_hanh": _ngay(doc.get("issueDate")),
        "ngay_hieu_luc": _ngay(doc.get("effFrom")),
        "ngay_het_hieu_luc": _ngay(doc.get("effTo")),
        "tinh_trang_nguon": tinh_trang,
        "ngay_kiem_tra": (hom_nay or date.today()).isoformat(),
        "linh_vuc": linh_vuc or None,
        "la_hop_nhat": int(bool(doc.get("isConsolidatedDocument"))),
        "nguon": "vbpl.vn",
        "url_goc": url,
    }
    meta = {k: v for k, v in meta.items() if v not in (None, "")}

    chu = html_sang_chu(content_html) if content_html else ""
    if len(chu) < 200:
        raise LoiThuThap(
            "Trang không có toàn văn dạng chữ (có thể chỉ có bản PDF/scan). Hãy tải tệp từ vbpl.vn và dùng 'phapluat nhap'."
        )

    for k, ten in (
        ("so_ky_hieu", "số ký hiệu"),
        ("co_quan_ban_hanh", "cơ quan ban hành"),
        ("ngay_ban_hanh", "ngày ban hành"),
        ("ngay_hieu_luc", "ngày có hiệu lực"),
        ("tinh_trang_nguon", "tình trạng hiệu lực"),
    ):
        if k not in meta:
            canh_bao.append(f"vbpl.vn không ghi {ten}.")

    header = parse_text(chu).header
    if header.get("trich_yeu") and bo_dau(header["trich_yeu"]) == bo_dau(meta.get("trich_yeu", "")):
        # Cùng chữ với tiêu đề trang: lấy cách viết hoa/thường của chính văn bản.
        meta["trich_yeu"] = header["trich_yeu"]
    dau = re.sub(r"\s+", "", chu[:3000]).lower()
    if so and re.sub(r"\s+", "", so).lower() not in dau:
        canh_bao.append(f"Không thấy số ký hiệu {so} ở phần đầu toàn văn: cần đối chiếu đúng văn bản.")

    if _nhac_phu_luc_kem_theo(chu) and not re.search(r"^\s*(PHỤ LỤC|Phụ lục)\b", chu, re.M):
        meta["thieu_phu_luc"] = 1
        canh_bao.append("Văn bản nhắc tới phụ lục kèm theo nhưng toàn văn trên trang không có phụ lục.")
    tep_khac = [
        r.get("fileTitle") or r.get("fileName")
        for r in (doc.get("documentRelatedList") or [])
        if not str(r.get("fileName") or "").endswith("_body_content.html")
    ]
    if tep_khac:
        canh_bao.append(
            "Trang có tệp đính kèm chưa nhập (bản gốc hoặc phụ lục, cần xem trên trang): "
            + ", ".join(filter(None, tep_khac))
            + "."
        )
    if doc.get("docGroup") and doc.get("docGroup") != "VBQPPL":
        canh_bao.append(f"Nhóm văn bản trên vbpl.vn: {doc.get('docGroup')}.")
    tinh = re.search(r"\b(?:tỉnh|thành phố|TP\.)\s+(.+)$", co_quan)
    if re.search(r"HĐND|UBND|Hội đồng nhân dân|Ủy ban nhân dân|Uỷ ban nhân dân", co_quan) or (
        (doc.get("organization") or {}).get("orgType") not in (None, "0")
    ):
        if tinh:
            meta["tinh_ban_hanh_goc"] = tinh.group(1).strip()
        canh_bao.append(
            "Văn bản địa phương: cần bổ sung tỉnh/thành phố hiện nay (sau sắp xếp) và phạm vi áp dụng"
            + ("." if tinh else ", và tỉnh ban hành gốc.")
        )

    if canh_bao:
        meta["canh_bao"] = " ".join(canh_bao)
    return KetQua(meta=meta, chu=chu, canh_bao=canh_bao)


# ---------------------------------------------------------------------------
# Tìm trang chi tiết


def chuan_hoa_url(url: str) -> str:
    """Đưa url trang chi tiết (vi/en) về bản tiếng Việt; báo lỗi nếu không phải trang chi tiết."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.netloc not in ("vbpl.vn", "www.vbpl.vn"):
        raise LoiThuThap(f"Không phải đường dẫn vbpl.vn: {url}")
    m = RE_CHI_TIET.match(parts.path)
    if not m:
        raise LoiThuThap(f"Không phải trang chi tiết văn bản (dạng /van-ban/chi-tiet/...): {url}")
    return f"{BASE}/van-ban/chi-tiet/{m.group(1)}"


def manh_so_ky_hieu(so: str) -> str:
    """'31/2024/QH15' -> 'so-31-2024-qh15' như trong đường dẫn vbpl.vn."""
    s = bo_dau(so).replace("đ", "d")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return "so-" + s


_RE_SO_DAU_TIEN = re.compile(r"(?:^|-)(so-\d)")


def tim_trong_ds_url(urls, so: str) -> list[str]:
    """Trang có số ký hiệu đúng bằng `so`: chỉ xét cụm 'so-<số>' ĐẦU TIÊN trong tên trang
    (là số của chính văn bản), để không lấy nhầm văn bản sửa đổi hay hợp nhất có nhắc tới số đó."""
    manh = manh_so_ky_hieu(so)
    out = []
    for u in urls:
        m = RE_CHI_TIET.match(urllib.parse.urlsplit(u).path)
        if not m:
            continue
        slug = m.group(1).split("--")[0]
        first = _RE_SO_DAU_TIEN.search(slug)
        if first and slug.startswith(manh, first.start(1)) and slug[first.start(1) + len(manh) :][:1] in ("", "-"):
            out.append(u)
    return out


class ChiMucSitemap:
    """Danh sách trang chi tiết lấy từ sitemap của vbpl.vn, lưu trên máy."""

    def __init__(self, thu_muc: Path, bo_tai: BoTai):
        self.thu_muc = Path(thu_muc)
        self.bo_tai = bo_tai

    def _ds_sitemap(self) -> list[str]:
        f = self.thu_muc / "sitemap-index.txt"
        if f.exists():
            return f.read_text(encoding="utf-8").split()
        xml = self.bo_tai.tai(BASE + "/sitemap.xml").decode("utf-8", "replace")
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)
        self.thu_muc.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(locs), encoding="utf-8")
        return locs

    def _urls(self, sm: str, tai_moi: bool) -> list[str] | None:
        name = re.sub(r"[^A-Za-z0-9]+", "_", urllib.parse.urlsplit(sm).path).strip("_") + ".txt"
        f = self.thu_muc / name
        if f.exists():
            return f.read_text(encoding="utf-8").split()
        if not tai_moi:
            return None
        xml = self.bo_tai.tai(sm).decode("utf-8", "replace")
        locs = [u for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml) if "/chi-tiet/" in u]
        f.write_text("\n".join(locs), encoding="utf-8")
        return locs

    def tim(self, so: str, in_tien_do=print) -> list[str]:
        """Tìm trong các sitemap đã lưu; nếu chưa thấy thì tải dần từng sitemap còn thiếu, thấy là dừng."""
        ds = self._ds_sitemap()
        found: list[str] = []
        chua_co: list[str] = []
        for sm in ds:
            urls = self._urls(sm, tai_moi=False)
            if urls is None:
                chua_co.append(sm)
            else:
                found += [u for u in tim_trong_ds_url(urls, so) if u not in found]
        for sm in chua_co:
            if found:
                break
            in_tien_do(f"  đang đọc sơ đồ trang {sm} ...")
            found += [u for u in tim_trong_ds_url(self._urls(sm, tai_moi=True) or [], so) if u not in found]
        return found


# ---------------------------------------------------------------------------
# Thu thập


def doc_trang(html: str, url: str, hom_nay: date | None = None) -> KetQua:
    doc, content = tach_van_ban(html)
    return chuyen_doi(doc, content, url, hom_nay)


def thu_thap_url(conn, url: str, bo_tai: BoTai, luu_html: Path | None = None) -> tuple[int, KetQua]:
    from .store import upsert_document

    url = chuan_hoa_url(url)
    body = bo_tai.tai(url)
    if luu_html:
        luu_html.mkdir(parents=True, exist_ok=True)
        (luu_html / (url.rsplit("--", 1)[-1] + ".html")).write_bytes(body)
    kq = doc_trang(body.decode("utf-8", "replace"), url)
    parsed = parse_text(kq.chu)
    kq.so_dieu = sum(1 for u in parsed.walk() if u.loai == "dieu")
    if kq.so_dieu == 0:
        kq.canh_bao.append("Không tách được Điều nào: cần xem lại toàn văn.")
        kq.meta["canh_bao"] = " ".join(kq.canh_bao)
    doc_id = upsert_document(conn, kq.meta, parsed)
    return doc_id, kq
