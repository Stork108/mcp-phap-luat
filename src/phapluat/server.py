"""MCP server tra cứu văn bản pháp luật.

Chạy cục bộ (Claude Code trên máy):   phapluat serve
Chạy trên cloud qua HTTPS có khóa:     phapluat serve --http --port 8000
  (đặt biến môi trường PHAPLUAT_TOKEN; client gửi 'Authorization: Bearer <token>')
"""

from __future__ import annotations

import os
import sqlite3

from mcp.server.fastmcp import FastMCP

from . import tools
from .db import connect

INSTRUCTIONS = """Tra cứu văn bản pháp luật Việt Nam từ kho dữ liệu riêng.
Thứ tự gợi ý: tim_van_ban -> xem_muc_luc -> trich_dieu_khoan hoặc lay_toan_van.
Khi tra bằng số ký hiệu, chỉ truyền số ký hiệu (ví dụ '59/2020/QH14'); khi tra bằng tên, chỉ truyền tên.
Số ký hiệu văn bản địa phương thường trùng giữa nhiều tỉnh: luôn kiểm tra cơ quan ban hành.
Khi trả lời người dùng: nêu rõ số ký hiệu, Điều, Khoản; trích nguyên văn; nêu tình trạng hiệu lực.
Nếu kết quả ghi 'Cần kiểm tra' hoặc có cảnh báo, phải nói rõ cho người dùng, không tự khẳng định."""

mcp = FastMCP("phap-luat", instructions=INSTRUCTIONS)

_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
    return _conn


@mcp.tool()
def tim_van_ban(
    tu_khoa: str,
    loai_van_ban: str | None = None,
    co_quan: str | None = None,
    tinh: str | None = None,
    linh_vuc: str | None = None,
    tu_ngay: str | None = None,
    den_ngay: str | None = None,
    bao_gom_het_hieu_luc: bool = False,
    gioi_han: int = 10,
    pham_vi: str = "mac_dinh",
) -> str:
    """Tìm văn bản theo từ khóa (có dấu hoặc không dấu) hoặc theo số ký hiệu.

    Mặc định bỏ qua văn bản đã hết hiệu lực toàn bộ. Ngày theo dạng YYYY-MM-DD.
    Kết quả kèm tình trạng hiệu lực và Điều khớp nhất.
    Phạm vi: mặc định chỉ văn bản trung ương; nêu tinh (ví dụ 'Hồ Chí Minh', 'Đồng Nai', hoặc tỉnh cũ
    'Bình Dương') thì thêm văn bản HĐND/UBND của tỉnh đó. pham_vi: 'mac_dinh', 'trung_uong',
    'dia_phuong' (chỉ văn bản địa phương) hoặc 'tat_ca'. Tìm theo số ký hiệu luôn xét mọi phạm vi.
    """
    return tools.tim_van_ban(
        _db(), tu_khoa, loai_van_ban, co_quan, tinh, linh_vuc, tu_ngay, den_ngay, bao_gom_het_hieu_luc, gioi_han,
        pham_vi,
    )


@mcp.tool()
def xem_muc_luc(van_ban: str, co_quan: str | None = None) -> str:
    """Xem thông tin và mục lục Phần/Chương/Mục/Điều của một văn bản.

    van_ban: số ký hiệu (ví dụ '45/2019/QH14') HOẶC tên văn bản, không ghép cả hai.
    """
    return tools.xem_muc_luc(_db(), van_ban, co_quan)


@mcp.tool()
def lay_toan_van(van_ban: str, co_quan: str | None = None, trang: int = 1) -> str:
    """Lấy toàn văn một văn bản, chia trang nếu dài (khoảng 15.000 ký tự mỗi trang)."""
    return tools.lay_toan_van(_db(), van_ban, co_quan, trang)


@mcp.tool()
def tra_cuu_tuan_thu(
    tinh_huong: str,
    linh_vuc: str | None = None,
    gioi_han: int = 8,
    tinh: str | None = None,
    pham_vi: str = "mac_dinh",
) -> str:
    """Tìm các Điều liên quan nhất tới một tình huống, chỉ trong văn bản đang có hiệu lực.

    Trả về nguyên văn để phân tích; công cụ không tự kết luận có tuân thủ hay không.
    Mặc định chỉ văn bản trung ương; nêu tinh để thêm văn bản địa phương của tỉnh đó (xem tim_van_ban).
    """
    return tools.tra_cuu_tuan_thu(_db(), tinh_huong, linh_vuc, gioi_han, tinh, pham_vi)


@mcp.tool()
def trich_dieu_khoan(
    van_ban: str,
    dieu: str,
    khoan: str | None = None,
    diem: str | None = None,
    co_quan: str | None = None,
) -> str:
    """Trích nguyên văn một Điều, Khoản hoặc Điểm, kèm cảnh báo nếu phần đó đã bị sửa đổi, thay thế, bãi bỏ."""
    return tools.trich_dieu_khoan(_db(), van_ban, dieu, khoan, diem, co_quan)


@mcp.tool()
def kiem_tra_hieu_luc(danh_sach_so_ky_hieu: list[str]) -> str:
    """Kiểm tra tình trạng hiệu lực của một hoặc nhiều văn bản theo số ký hiệu."""
    return tools.kiem_tra_hieu_luc(_db(), danh_sach_so_ky_hieu)


@mcp.tool()
def van_ban_lien_quan(van_ban: str, co_quan: str | None = None) -> str:
    """Liệt kê văn bản căn cứ, hướng dẫn, sửa đổi, thay thế, hợp nhất liên quan tới một văn bản."""
    return tools.van_ban_lien_quan(_db(), van_ban, co_quan)


def run_stdio() -> None:
    mcp.run("stdio")


def run_http(host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    token = os.environ.get("PHAPLUAT_TOKEN")
    if not token or len(token) < 24:
        raise SystemExit("Cần đặt PHAPLUAT_TOKEN (ít nhất 24 ký tự) trước khi chạy qua HTTP.")

    class BearerAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.headers.get("authorization") != f"Bearer {token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuth)
    uvicorn.run(app, host=host, port=port)
