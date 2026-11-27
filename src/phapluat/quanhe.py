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


def chuan_hoa_chu(text: str) -> str:
    """Gộp số ký hiệu bị tách bởi dấu cách ('105/ 2016/QH13' -> '105/2016/QH13'). Chỉ dùng để đọc quan hệ."""
    return re.sub(r"(?<=\d)\s*/\s+(?=\d{4}/|[A-ZĐ])|(?<=\d{4})\s+/\s*(?=[A-ZĐ])", "/", text)


def tach_so(text: str) -> list[str]:
    """Số ký hiệu văn bản trong câu. Bỏ số mẫu biểu ('Mẫu số 01/BK-ĐCTT') và công văn không có năm;
    số không có năm chỉ nhận khi là văn bản hợp nhất (VBHN)."""
    out = []
    for m in RE_SO.finditer(text):
        so = m.group(1)
        if not ("-" in so or re.search(r"QH|UBTVQH", so)):
            continue
        truoc = text[max(0, m.start() - 30) : m.start()]
        if re.search(r"mẫu(?:\s+số)?\s*$", truoc, re.I) and not re.search(_LOAI + r"\s+mẫu\s+số\s*$", truoc, re.I):
            continue
        if not re.search(r"/\d{4}/", so) and "VBHN" not in so:
            continue
        out.append(so)
    return out


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
    r"(?P<khac>(?:(?:khoản|Khoản)\s+\d+[a-zđ]?\s+)?(?:(?:Tiểu mục|tiểu mục|Mục|mục)\s+[IVXLC\d]+\s+(?:của\s+)?)?"
    r"(?:(?:Chương|Phần|Phụ lục)\s+[IVXLC\d]+[A-Z]?\b(?:\s+(?:của\s+)?(?:Phần|Chương)\s+[IVXLC\d]+\b)?"
    r"|(?:Mục|Tiểu mục)\s+[IVXLC\d]+\s+(?:của\s+)?(?:Chương|Phần|Phụ lục)\s+[IVXLC\d]+\b))"
    r"|(?P<diem>(?:điểm|Điểm)\s+[a-zđ](?:\.\d+)?(?![\w])(?:\s*(?:,|và)\s*(?:điểm\s+)?[a-zđ](?:\.\d+)?(?![\w]))*)"
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
        if m.group("khac"):
            out.append(re.sub(r"\s+", " ", m.group("khac")).strip())
            cho_khoan, cho_diem = [], []
        elif m.group("diem"):
            cho_diem += re.findall(r"(?<![\w.])[a-zđ](?:\.\d+)?(?![\w])", m.group("diem").split(None, 1)[1])
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


RE_LOAI = re.compile(_LOAI)
RE_LOAI_CUOI = re.compile(_LOAI + r"(?:\s+[^\d;]{0,100}?)?\s+(?:số\s+)?$")


RE_DONG_TU_MO_TA = re.compile(r"sửa đổi|bổ sung|bãi bỏ|hướng dẫn|quy định chi tiết|thi hành|thay thế", re.I)
RE_TEN_SUA_DOI = re.compile(r"(?:^|,|;|\bvà|\bhoặc)\s*" + _LOAI + r"\s+(?:sửa đổi|bổ sung)", re.I)


def tach_muc_van_ban(part: str) -> list[tuple[str, str]]:
    """Các văn bản bị tác động trong một mệnh đề, kèm đoạn chữ đứng trước (chứa vị trí Điều/Khoản).

    Văn bản đầu tiên luôn được nhận. Văn bản sau chỉ được nhận khi văn bản liền trước được nhận và
    đoạn giữa hai văn bản không phải phần mô tả: không chứa tên loại văn bản khác, không chứa động từ
    'sửa đổi, bổ sung, hướng dẫn, quy định chi tiết...', và kết thúc bằng dấu phẩy, 'và', 'hoặc'.
    Ngoại lệ: tên văn bản dạng 'và Luật sửa đổi, bổ sung ... của Luật X số Y' được nhận, không kèm vị trí."""
    out: list[tuple[str, str]] = []
    prev_end = 0
    prev_ok = True
    for m in RE_SO.finditer(part):
        so = m.group(1)
        if so not in tach_so(part[max(0, m.start() - 30) : m.end()]):
            continue
        truoc = part[prev_end : m.start()]
        loais = list(RE_LOAI.finditer(truoc))
        seg = truoc[: loais[-1].start()] if loais else truoc
        if not out and prev_end == 0:
            ok = True
        elif not prev_ok:
            ok = False
        elif RE_TEN_SUA_DOI.search(seg):
            ok, seg = True, ""
        elif RE_LOAI.search(seg):
            ok = False
        elif RE_DONG_TU_MO_TA.search(seg):
            # có động từ mô tả: chỉ nhận khi nối bằng 'và', 'hoặc', ';' (văn bản ngang hàng), không nhận vị trí
            ok = re.search(r"(?:\bvà|\bhoặc|;)\s*$", seg) is not None
            seg = ""
        else:
            s2 = re.sub(r"\s*(?:của|tại)\s*$", "", seg).rstrip()
            ok = s2 == "" or re.search(r"(?:,|:|\bvà|\bhoặc)$", s2) is not None or bool(
                re.search(r"(?:Điều|điều)\s+\d+[a-zđ]?$", s2)
            )
            if ok and not re.search(r"(?:Điều|điều)\s+\d", seg):
                seg = ""
        if ok:
            out.append((so, seg))
        prev_ok = ok
        prev_end = m.end()
    return out


RE_LENH_CON = re.compile(r"^\s*(?:[a-zđ]\)|[-–+])\s*(Cụm từ|cụm từ|Thay thế|Thay|Bãi bỏ|Sửa đổi|Bổ sung)\b")


def doc_sua_doi(dieu_so: str, dieu_text: str, so_dich_mac_dinh: str | None) -> list[QuanHe]:
    """Đọc lệnh sửa đổi, bổ sung, bãi bỏ, thay cụm từ trong một Điều.
    Văn bản đích: văn bản nêu trong lệnh (ngoài ngoặc kép), nếu không có thì văn bản nêu ở lệnh cha
    hoặc ở tên Điều, hoặc văn bản mặc định (từ trích yếu của văn bản sửa đổi)."""
    lines = dieu_text.split("\n")
    tieu_de = lines[0] if lines else ""
    so_tieu_de = tach_so(tieu_de)
    so_dich = so_tieu_de[0] if so_tieu_de else so_dich_mac_dinh
    ctx_dich = so_dich
    out: list[QuanHe] = []
    dieu_cha: str | None = None
    for i, line in _ngoai_ngoac_kep(lines):
        if i == 0:
            continue
        m = RE_LENH_SUA.match(line) or RE_LENH_CON.match(line)
        if not m:
            continue
        la_cha = bool(re.match(r"^\s*\d+[a-zđ]?\.", line))
        if la_cha:
            ctx_dich, dieu_cha = so_dich, None
        loai = _loai_tu_dong_tu(m.group(1))
        cau = re.split(r"\bnhư sau\b|:\s*$", line)[0]
        co_dich_rieng = False
        for part in cau.split(";"):
            items = tach_muc_van_ban(part)
            if items:
                co_dich_rieng = True
                for so, seg in items:
                    for vt in _vi_tri_trong(seg) or [None]:
                        out.append(QuanHe(loai, so, vt, f"Điều {dieu_so}", _cat(line)))
                if la_cha:
                    ctx_dich = items[0][0]
            elif ctx_dich:
                vts = _vi_tri_trong(part, None if la_cha else dieu_cha)
                if not vts and la_cha and bo_dau(m.group(1)).startswith(("thay", "cum tu")):
                    continue
                for vt in vts or [None]:
                    out.append(QuanHe(loai, ctx_dich, vt, f"Điều {dieu_so}", _cat(line)))
        if la_cha and not co_dich_rieng:
            ds = RE_DIEU.findall(cau)
            dieu_cha = ds[-1] if ds else None
    return out


RE_THAY_THE = re.compile(r"(?:này|này)\s+thay thế|thay thế\s+(?:các\s+)?" + _LOAI, re.I)
RE_BAI_BO = re.compile(
    r"bãi bỏ\s+(?:toàn bộ\s+)?(?:các\s+)?(?:" + _LOAI + r"|Điều|điều|khoản|điểm|văn bản|quy định)", re.I
)
RE_HET_HL = re.compile(r"hết hiệu lực", re.I)
RE_BO_QUA_HL = re.compile(r"tiếp tục|Kể từ thời điểm", re.I)
RE_MOC_THOI_GIAN = re.compile(
    r"(?:từ|đến|kể từ|cho đến)\s+(?:ngày|khi|thời điểm)\s+" + _LOAI + r"\s+số\s+\S+\s+(?:\S+\s+){0,12}?hết hiệu lực", re.I
)
RE_THAY_MAU = re.compile(
    r"[Mm]ẫu(?:\s+số)?\s+([0-9A-Za-zĐđ/\-]+)[^;]*?kèm theo\s+" + _LOAI + r"\s+số\s+(\S+?)(?=[\s,;.]|$)"
)


def doc_hieu_luc(dieu_so: str, dieu_text: str) -> list[QuanHe]:
    """Đọc điều khoản hiệu lực: văn bản nào bị thay thế, bãi bỏ, hết hiệu lực.
    Chỉ nhận khi động từ gắn trực tiếp với văn bản ('Luật này thay thế Luật ... số', 'Bãi bỏ quy định tại
    Điều 6 Nghị định số', 'Nghị định số ... hết hiệu lực', hoặc danh sách 'Bãi bỏ quy định tại:' kèm các mục).
    Bỏ qua quy định chuyển tiếp, mốc thời gian ('có hiệu lực từ ngày Nghị quyết số X hết hiệu lực'),
    chữ trong ngoặc kép. Lệnh thay cụm từ do doc_sua_doi đọc; thay mẫu biểu ghi là sửa đổi mẫu."""
    out: list[QuanHe] = []
    dong_tu_ds: str | None = None
    lines = dieu_text.split("\n")
    for i, line in _ngoai_ngoac_kep(lines):
        if i == 0:
            continue
        if re.match(r"^\s*\d+[a-zđ]?\.", line):
            dong_tu_ds = None
        if RE_BO_QUA_HL.search(line) or RE_MOC_THOI_GIAN.search(line):
            continue
        if RE_LENH_SUA.match(line) and re.search(r"cụm từ", line, re.I) or RE_LENH_CON.match(line):
            continue
        if re.search(r"thay thế\s+(?:các\s+)?mẫu", line, re.I):
            for mm in RE_THAY_MAU.finditer(line):
                if tach_so(mm.group(2)):
                    out.append(QuanHe("sua_doi", tach_so(mm.group(2))[0], f"mẫu số {mm.group(1)}", f"Điều {dieu_so}", _cat(line)))
            continue
        if line.rstrip().endswith(":"):
            dl = bo_dau(line)
            hd = "thay_the" if "thay the" in dl else "bai_bo" if "bai bo" in dl else "het_hieu_luc" if "het hieu luc" in dl else None
            if hd:
                dong_tu_ds = hd
                if not tach_so(line):
                    continue
        dt = None
        if RE_THAY_THE.search(line):
            dt = "thay_the"
        elif RE_BAI_BO.search(line):
            dt = "bai_bo"
        elif RE_HET_HL.search(line):
            dt = "het_hieu_luc"
        la_muc = bool(re.match(r"^\s*[a-zđ]\)|^\s*[-–+]", line))
        loai = (dong_tu_ds if la_muc and dong_tu_ds else None) or dt
        if not loai:
            continue
        pos_hl = [h.start() for h in RE_HET_HL.finditer(line)]
        off = 0
        for muc in line.split(";"):
            for so, seg in tach_muc_van_ban(muc):
                if loai == "het_hieu_luc" and not la_muc:
                    vi = off + muc.find(so)
                    if not any(p > vi for p in pos_hl):
                        continue
                seg = re.split(r"(?:này|này)\s+(?:thay thế|bãi bỏ)|[Bb]ãi bỏ|thay thế", seg)[-1]
                for vt in _vi_tri_trong(seg) or [None]:
                    out.append(QuanHe(loai, so, vt, f"Điều {dieu_so}", _cat(muc)))
            off += len(muc) + 1
    return out


def doc_van_ban(conn: sqlite3.Connection, doc: sqlite3.Row) -> list[QuanHe]:
    units = conn.execute(
        "SELECT loai, so, tieu_de, noi_dung, duong_dan FROM units WHERE doc_id = ? ORDER BY thu_tu", (doc["id"],)
    ).fetchall()
    ban_than = chuan_hoa_so_ky_hieu(doc["so_ky_hieu"])
    ty = chuan_hoa_chu(doc["trich_yeu"] or "")
    out: list[QuanHe] = []

    so_ty = [s for s in tach_so(ty) if chuan_hoa_so_ky_hieu(s) != ban_than]
    # Văn bản sửa đổi: trích yếu bắt đầu bằng 'Sửa đổi', 'Bổ sung', 'Bãi bỏ', 'Đính chính'
    # (không tính 'Hướng dẫn ... Nghị định số X sửa đổi, bổ sung ...').
    la_sua_doi = bool(re.match(r"\s*(?:" + _LOAI + r"\s+)?(?:sửa đổi|bổ sung|bãi bỏ|đính chính)", ty, re.I))
    so_dich_mac_dinh = so_ty[0] if (la_sua_doi and len(so_ty) == 1) else None

    for u in units:
        noi_dung = chuan_hoa_chu(u["noi_dung"])
        if u["loai"] == "mo_dau":
            if doc["la_hop_nhat"]:
                for line in noi_dung.split("\n"):
                    if line.strip().startswith("Căn cứ"):
                        continue
                    for s in tach_so(line):
                        if chuan_hoa_so_ky_hieu(s) != ban_than:
                            out.append(QuanHe("hop_nhat", s, None, None, _cat(line)))
            else:
                for line in noi_dung.split("\n"):
                    if line.strip().startswith("Căn cứ"):
                        ds = tach_so(line)
                        if ds:
                            out.append(QuanHe("can_cu", ds[0], None, None, _cat(line)))
        elif u["loai"] == "dieu" and u["duong_dan"].count("Điều") == 1 and not doc["la_hop_nhat"]:
            tieu_de = u["tieu_de"] or ""
            hl = bool(RE_DIEU_HIEU_LUC.search(tieu_de))
            if hl:
                out += doc_hieu_luc(u["so"], noi_dung)
            if hl or la_sua_doi or re.search(r"sửa đổi|bổ sung|bãi bỏ|thay thế", tieu_de, re.I):
                out += doc_sua_doi(u["so"], noi_dung, so_dich_mac_dinh)

    co_vi_tri = {q.dst_so for q in out if q.loai in ("sua_doi", "bai_bo") and q.dst_vi_tri}
    if not doc["la_hop_nhat"]:
        if la_sua_doi:
            for s in so_ty:
                if s not in co_vi_tri:
                    out.append(QuanHe("sua_doi", s, None, None, _cat(ty)))
        if re.match(r"\s*(Quy định chi tiết|Hướng dẫn)", ty, re.I):
            for s in so_ty:
                out.append(QuanHe("huong_dan", s, None, None, _cat(ty)))

    # bỏ trùng, bỏ tự trỏ về chính mình, bỏ dòng không vị trí khi đã có dòng có vị trí cùng loại, cùng đích
    co_vt = {(q.loai, chuan_hoa_so_ky_hieu(q.dst_so), q.src_vi_tri) for q in out if q.dst_vi_tri}
    out = [
        q
        for q in out
        if q.dst_vi_tri
        or q.loai in ("het_hieu_luc", "thay_the")  # hết hiệu lực toàn bộ khác với một phần: giữ cả hai
        or (q.loai, chuan_hoa_so_ky_hieu(q.dst_so), q.src_vi_tri) not in co_vt
    ]
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
