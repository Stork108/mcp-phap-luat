"""Dòng lệnh: phapluat <lệnh>. Gõ 'phapluat -h' để xem hướng dẫn."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .db import connect, default_db_path
from .extract import read_text
from .parser import parse_text
from .status import chuan_hoa_tinh_trang
from .store import add_relation, find_documents, upsert_document

FIELD_ARGS = {
    "so_ky_hieu": "--so-ky-hieu",
    "co_quan_ban_hanh": "--co-quan",
    "loai_van_ban": "--loai",
    "trich_yeu": "--trich-yeu",
    "ngay_ban_hanh": "--ngay-ban-hanh",
    "ngay_hieu_luc": "--ngay-hieu-luc",
    "ngay_het_hieu_luc": "--ngay-het-hieu-luc",
    "tinh_trang_nguon": "--tinh-trang",
    "ngay_kiem_tra": "--ngay-kiem-tra",
    "linh_vuc": "--linh-vuc",
    "nguon": "--nguon",
    "url_goc": "--url",
    "tinh_ban_hanh_goc": "--tinh-goc",
    "tinh_hien_nay": "--tinh-hien-nay",
    "pham_vi_ap_dung": "--pham-vi",
}

BAT_BUOC = ("so_ky_hieu", "co_quan_ban_hanh", "trich_yeu")


def nhap_tep(conn, path: str, meta: dict) -> tuple[int, list[str]]:
    text, warnings = read_text(path)
    parsed = parse_text(text)
    guessed = []
    for k, v in parsed.header.items():
        if not meta.get(k):
            meta[k] = v
            guessed.append(k)
    missing = [k for k in BAT_BUOC if not meta.get(k)]
    if missing:
        raise ValueError(f"{path}: thiếu {', '.join(missing)} (không đọc được từ văn bản, hãy nhập bằng tham số).")
    if meta.get("tinh_trang_nguon") and not chuan_hoa_tinh_trang(meta["tinh_trang_nguon"]):
        raise ValueError(
            f"Tình trạng '{meta['tinh_trang_nguon']}' không hợp lệ. Dùng: Còn hiệu lực, Hết hiệu lực một phần, "
            "Chưa có hiệu lực, Hết hiệu lực toàn bộ."
        )
    notes = list(warnings)
    if guessed:
        notes.append("Tự đọc từ phần đầu văn bản, cần đối chiếu nguồn: " + ", ".join(guessed) + ".")
    if notes:
        meta["canh_bao"] = " ".join(filter(None, [meta.get("canh_bao"), *notes]))
    if "PHỤ LỤC" not in text and "phụ lục" in text.lower() and "kèm theo" in text.lower():
        meta.setdefault("thieu_phu_luc", 1)
    doc_id = upsert_document(conn, meta, parsed)
    n_dieu = sum(1 for u in parsed.walk() if u.loai == "dieu")
    return doc_id, [f"{meta['so_ky_hieu']}: {n_dieu} điều"] + notes


def _thu_thap_vbpl(conn, a) -> int:
    from .thuthap_vbpl import BoTai, ChiMucSitemap, LoiThuThap, thu_thap_url

    nguon = list(a.nguon)
    if a.tu_tep:
        for line in Path(a.tu_tep).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                nguon.append(line)
    if not nguon:
        print("Cần ít nhất một url trang chi tiết vbpl.vn hoặc một số ký hiệu (hoặc --tu-tep).")
        return 1
    bo_tai = BoTai(do_tre=a.do_tre, toi_da=a.toi_da)
    chi_muc = ChiMucSitemap(default_db_path().parent / "vbpl-sitemap", bo_tai)
    luu = Path(a.luu_html) if a.luu_html else None
    ok = loi = 0
    for n in nguon:
        try:
            if n.startswith("http"):
                urls = [n]
            else:
                print(f"Tìm {n} trong sơ đồ trang vbpl.vn ...")
                urls = chi_muc.tim(n)
                if not urls:
                    raise LoiThuThap(f"không thấy trang chi tiết nào có số ký hiệu {n} trong sơ đồ trang.")
                if len(urls) > 1:
                    raise LoiThuThap(
                        f"có {len(urls)} trang cùng số ký hiệu {n}, hãy chọn một url:\n    " + "\n    ".join(urls)
                    )
            _, kq = thu_thap_url(conn, urls[0], bo_tai, luu)
            print(
                f"OK   {kq.meta['so_ky_hieu']} ({kq.meta.get('co_quan_ban_hanh', '')}): {kq.so_dieu} điều, "
                f"{kq.meta.get('tinh_trang_nguon', 'chưa rõ tình trạng')}. {kq.meta['url_goc']}"
            )
            for c in kq.canh_bao:
                print(f"     Cảnh báo: {c}")
            ok += 1
        except LoiThuThap as e:
            print(f"LỖI {n}: {e}")
            loi += 1
    print(f"Xong: {ok} văn bản nhập được, {loi} lỗi. Đã tải {bo_tai.so_lan} trang.")
    return 0 if loi == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="phapluat", description="Kho tra cứu văn bản pháp luật cá nhân")
    ap.add_argument("--db", help=f"đường dẫn tệp kho dữ liệu (mặc định {default_db_path()})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("nhap", help="nhập một tệp văn bản (.docx, .txt, .html, .pdf)")
    p.add_argument("tep")
    for f, flag in FIELD_ARGS.items():
        p.add_argument(flag, dest=f)

    p = sub.add_parser("nhap-danh-muc", help="nhập nhiều tệp theo bảng CSV (cột 'tep' + các cột thông tin)")
    p.add_argument("csv")

    p = sub.add_parser("quan-he", help="ghi quan hệ: văn bản nguồn <loai> văn bản đích")
    p.add_argument("so_nguon")
    p.add_argument("loai", choices=["can_cu", "huong_dan", "sua_doi", "thay_the", "bai_bo", "dinh_chinh",
                                    "hop_nhat", "tiep_tuc_ap_dung"])
    p.add_argument("so_dich")
    p.add_argument("--co-quan-nguon")
    p.add_argument("--co-quan-dich")
    p.add_argument("--vi-tri-nguon")
    p.add_argument("--vi-tri-dich")
    p.add_argument("--ghi-chu")

    sub.add_parser("thong-ke", help="thống kê kho và danh sách văn bản cần kiểm tra")
    p = sub.add_parser("khao-sat-vbpl", help="tải vài trang vbpl.vn để phân tích cấu trúc (chạy trên máy cá nhân)")
    p.add_argument("--so-trang", type=int, default=15)
    p.add_argument("--buoc", type=int, default=1, choices=[1, 2], help="2: đọc sơ đồ trang và vài trang chi tiết")
    p = sub.add_parser(
        "thu-thap-vbpl",
        help="tải toàn văn và thuộc tính từ trang chi tiết vbpl.vn (theo url hoặc số ký hiệu) rồi nhập vào kho",
    )
    p.add_argument("nguon", nargs="*", help="url https://vbpl.vn/van-ban/chi-tiet/... hoặc số ký hiệu, ví dụ 31/2024/QH15")
    p.add_argument("--tu-tep", help="tệp chữ, mỗi dòng một url hoặc số ký hiệu (dòng bắt đầu bằng # bị bỏ qua)")
    p.add_argument("--do-tre", type=float, default=4.0, help="số giây giữa hai lần tải (tối thiểu 4)")
    p.add_argument("--toi-da", type=int, default=100, help="số lần tải tối đa trong một lần chạy (mặc định 100)")
    p.add_argument("--luu-html", help="thư mục lưu nguyên trạng trang đã tải (để đối chiếu)")
    p = sub.add_parser("serve", help="chạy MCP server")
    p.add_argument("--http", action="store_true", help="chạy qua HTTP (cloud), cần PHAPLUAT_TOKEN")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)

    a = ap.parse_args(argv)
    if a.db:
        import os

        os.environ["PHAPLUAT_DB"] = a.db

    if a.cmd == "serve":
        from . import server

        server.run_http(a.host, a.port) if a.http else server.run_stdio()
        return 0
    if a.cmd == "khao-sat-vbpl":
        from .khaosat import chay, chay_buoc_2

        out = chay_buoc_2() if a.buoc == 2 else chay(max_pages=a.so_trang)
        print(f"Đã lưu kết quả khảo sát vào thư mục: {out.resolve()}")
        print("Hãy nén thư mục này (chuột phải > Send to > Compressed folder) và gửi lại trong thread.")
        return 0

    conn = connect()
    if a.cmd == "thu-thap-vbpl":
        return _thu_thap_vbpl(conn, a)
    if a.cmd == "nhap":
        meta = {f: getattr(a, f) for f in FIELD_ARGS if getattr(a, f)}
        meta.setdefault("nguon", "thu-cong")
        _, notes = nhap_tep(conn, a.tep, meta)
        print("\n".join(notes))
    elif a.cmd == "nhap-danh-muc":
        base = Path(a.csv).parent
        ok = loi = 0
        with open(a.csv, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                tep = row.pop("tep", "").strip()
                meta = {k: v.strip() for k, v in row.items() if k in FIELD_ARGS and v and v.strip()}
                meta.setdefault("nguon", "thu-cong")
                try:
                    _, notes = nhap_tep(conn, str(base / tep), meta)
                    print("OK  ", " | ".join(notes))
                    ok += 1
                except Exception as e:  # noqa: BLE001 - báo lỗi từng dòng, không dừng cả lô
                    print("LỖI ", tep, "–", e)
                    loi += 1
        print(f"Xong: {ok} văn bản nhập được, {loi} lỗi.")
    elif a.cmd == "quan-he":
        src = find_documents(conn, a.so_nguon, a.co_quan_nguon)
        if len(src) != 1:
            print(f"Văn bản nguồn '{a.so_nguon}': tìm thấy {len(src)} văn bản, cần đúng 1 (thêm --co-quan-nguon).")
            return 1
        add_relation(conn, src[0]["id"], a.loai, a.so_dich, a.co_quan_dich, a.vi_tri_nguon, a.vi_tri_dich, a.ghi_chu)
        print("Đã ghi quan hệ.")
    elif a.cmd == "thong-ke":
        from .status import CAN_KIEM_TRA, tinh_trang

        docs = conn.execute("SELECT * FROM documents ORDER BY so_ky_hieu").fetchall()
        n_dieu = conn.execute("SELECT count(*) FROM units WHERE loai='dieu'").fetchone()[0]
        print(f"Kho: {len(docs)} văn bản, {n_dieu} điều.")
        can = [d for d in docs if tinh_trang(dict(d))[0] == CAN_KIEM_TRA or d["canh_bao"]]
        if can:
            print(f"\n{len(can)} văn bản cần kiểm tra:")
            for d in can:
                tt, ly_do = tinh_trang(dict(d))
                print(f"- {d['so_ky_hieu']} ({d['co_quan_ban_hanh']}): {tt}. {ly_do or ''} {d['canh_bao'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
