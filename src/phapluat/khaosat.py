"""Khảo sát cấu trúc trang vbpl.vn để viết bộ thu thập.

Chạy trên máy người dùng (máy chủ cloud không truy cập được vbpl.vn).
Tải rất ít trang, mỗi trang cách nhau vài giây, tôn trọng robots.txt,
và lưu nguyên trạng vào thư mục 'khao-sat-vbpl' để phân tích.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

USER_AGENT = "mcp-phap-luat/0.1 (cong cu tra cuu ca nhan; thu thap cham)"
BASE = "https://vbpl.vn"
SEEDS = [
    "https://vbpl.vn/",
    "https://vbpl.vn/TW/pages/home.aspx",
]
# Từ khóa nhận diện đường dẫn tới trang văn bản / tìm kiếm
LINK_HINTS = re.compile(r"(ItemID=|toanvan|thuoctinh|luocdo|vbpq|van-ban|/api/|search|timkiem)", re.I)


def _fetch(url: str, timeout: int = 30) -> tuple[int, str, bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "vi"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.geturl(), resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, url, e.read() if hasattr(e, "read") else b"", dict(e.headers or {})


def _safe_name(url: str, i: int) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", urllib.parse.urlsplit(url).path + "_" + urllib.parse.urlsplit(url).query)
    return f"{i:02d}{s[:80]}.html"


def chay(out_dir: str | Path = "khao-sat-vbpl", max_pages: int = 15, delay: float = 4.0) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"user_agent": USER_AGENT, "pages": []}

    status, final, body, headers = _fetch(BASE + "/robots.txt")
    (out / "robots.txt").write_bytes(body)
    report["robots"] = {"status": status, "final_url": final}
    rp = urllib.robotparser.RobotFileParser()
    if status == 200:
        rp.parse(body.decode("utf-8", "replace").splitlines())
    else:
        rp.parse([])

    queue = list(SEEDS)
    seen: set[str] = set()
    i = 0
    while queue and i < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if not rp.can_fetch(USER_AGENT, url):
            report["pages"].append({"url": url, "bo_qua": "robots.txt không cho phép"})
            continue
        time.sleep(delay)
        status, final, body, headers = _fetch(url)
        name = _safe_name(final, i)
        (out / name).write_bytes(body)
        text = body.decode("utf-8", "replace")
        links = sorted(set(re.findall(r"""(?:href|src|action)\s*=\s*["']([^"']+)["']""", text)))
        abs_links = [urllib.parse.urljoin(final, l) for l in links]
        hinted = [l for l in abs_links if LINK_HINTS.search(l) and l.startswith(BASE)]
        report["pages"].append(
            {
                "url": url,
                "final_url": final,
                "status": status,
                "content_type": headers.get("Content-Type"),
                "bytes": len(body),
                "file": name,
                "so_link": len(abs_links),
                "link_goi_y": hinted[:60],
                "script": [l for l in abs_links if l.endswith(".js")][:30],
            }
        )
        i += 1
        # Ưu tiên mở vài trang văn bản cụ thể để thấy cấu trúc toàn văn/thuộc tính.
        for l in hinted:
            if l not in seen and len(queue) < 40:
                queue.append(l)

    (out / "bao-cao.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Bước 2: sơ đồ trang (sitemap) và vài trang chi tiết văn bản.
# robots.txt của vbpl.vn chặn /api/ và /Pages/, nên công cụ không bao giờ gọi các đường dẫn đó.

_CAM = ("/api/", "/Pages/")


def _locs(xml: str) -> list[str]:
    return [l.strip() for l in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)]


def chay_buoc_2(out_dir: str | Path = "khao-sat-vbpl-2", so_trang_chi_tiet: int = 4, delay: float = 4.0) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"user_agent": USER_AGENT, "sitemaps": [], "pages": []}

    status, final, body, _ = _fetch(BASE + "/robots.txt")
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines() if status == 200 else [])

    def allowed(url: str) -> bool:
        path = urllib.parse.urlsplit(url).path
        return url.startswith(BASE) and not any(path.startswith(c) for c in _CAM) and rp.can_fetch(USER_AGENT, url)

    # Sơ đồ trang gốc, rồi tối đa 3 sơ đồ con.
    queue = [BASE + "/sitemap.xml"]
    page_urls: list[str] = []
    n = 0
    while queue and n < 4:
        sm = queue.pop(0)
        time.sleep(delay)
        status, final, body, headers = _fetch(sm, timeout=60)
        n += 1
        name = f"sitemap_{n:02d}.xml"
        (out / name).write_bytes(body[:5_000_000])
        xml = body.decode("utf-8", "replace")
        locs = _locs(xml)
        is_index = "<sitemapindex" in xml
        report["sitemaps"].append(
            {"url": sm, "status": status, "file": name, "la_chi_muc": is_index, "so_loc": len(locs), "mau": locs[:30]}
        )
        if is_index:
            queue.extend(locs[:3])
        else:
            page_urls.extend(locs)

    # Chọn vài trang có vẻ là trang chi tiết văn bản (đường dẫn dài nhất, có chữ số).
    cands = [u for u in page_urls if allowed(u) and re.search(r"\d", urllib.parse.urlsplit(u).path)]
    cands.sort(key=lambda u: -len(urllib.parse.urlsplit(u).path))
    seen_shapes: set[str] = set()
    picked: list[str] = []
    for u in cands:
        shape = re.sub(r"\d+", "N", urllib.parse.urlsplit(u).path.rsplit("/", 1)[0])
        if shape in seen_shapes and len(picked) < 2:
            continue
        seen_shapes.add(shape)
        picked.append(u)
        if len(picked) >= so_trang_chi_tiet:
            break

    for i, u in enumerate(picked):
        time.sleep(delay)
        status, final, body, headers = _fetch(u)
        name = _safe_name(final, i)
        (out / name).write_bytes(body)
        text = body.decode("utf-8", "replace")
        report["pages"].append(
            {
                "url": u,
                "final_url": final,
                "status": status,
                "bytes": len(body),
                "file": name,
                "co_chu_dieu": "Điều 1" in text or "\\u0110i\\u1ec1u 1" in text,
                "co_so_ky_hieu": bool(re.search(r"\d+/\d{4}/[A-ZĐ]", text)),
            }
        )

    (out / "bao-cao.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
