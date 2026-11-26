"""Xác định tình trạng hiệu lực từ ngày tháng và ghi nhận của nguồn."""

from __future__ import annotations

from datetime import date

CON_HIEU_LUC = "Còn hiệu lực"
HET_MOT_PHAN = "Hết hiệu lực một phần"
CHUA_HIEU_LUC = "Chưa có hiệu lực"
HET_TOAN_BO = "Hết hiệu lực toàn bộ"
CAN_KIEM_TRA = "Cần kiểm tra"

_ALIASES = {
    "con hieu luc": CON_HIEU_LUC,
    "het hieu luc mot phan": HET_MOT_PHAN,
    "chua co hieu luc": CHUA_HIEU_LUC,
    "het hieu luc toan bo": HET_TOAN_BO,
    "het hieu luc": HET_TOAN_BO,
    "ngung hieu luc": CAN_KIEM_TRA,
    "ngung hieu luc mot phan": HET_MOT_PHAN,
}


def chuan_hoa_tinh_trang(raw: str | None) -> str | None:
    if not raw:
        return None
    from .textnorm import bo_dau

    return _ALIASES.get(bo_dau(raw), None)


def tinh_trang(doc: dict, hom_nay: date | None = None) -> tuple[str, str | None]:
    """Trả về (tình trạng, lý do cảnh báo nếu có).

    Tình trạng của nguồn được đối chiếu với ngày hiệu lực và ngày hết hiệu lực.
    Nếu hai cách cho kết quả khác nhau thì trả về 'Cần kiểm tra' thay vì tự kết luận.
    """
    hom_nay = hom_nay or date.today()
    today = hom_nay.isoformat()
    nguon = chuan_hoa_tinh_trang(doc.get("tinh_trang_nguon"))
    hl = doc.get("ngay_hieu_luc")
    het = doc.get("ngay_het_hieu_luc")

    theo_ngay = None
    if het and het <= today:
        theo_ngay = HET_TOAN_BO
    elif hl and hl > today:
        theo_ngay = CHUA_HIEU_LUC
    elif hl and hl <= today:
        theo_ngay = CON_HIEU_LUC  # hoặc hết một phần: chỉ nguồn mới biết

    if nguon is None and theo_ngay is None:
        return CAN_KIEM_TRA, "Chưa có thông tin hiệu lực từ nguồn chính thống."
    if nguon is None:
        return CAN_KIEM_TRA, f"Nguồn chưa ghi tình trạng; theo ngày tháng thì '{theo_ngay}'."
    if theo_ngay is None:
        return nguon, None
    if nguon == theo_ngay or (nguon == HET_MOT_PHAN and theo_ngay == CON_HIEU_LUC):
        return nguon, None
    if nguon == CON_HIEU_LUC and theo_ngay == CHUA_HIEU_LUC:
        return CAN_KIEM_TRA, f"Nguồn ghi '{nguon}' nhưng ngày hiệu lực {hl} chưa đến."
    return CAN_KIEM_TRA, f"Nguồn ghi '{nguon}' nhưng theo ngày tháng là '{theo_ngay}'."
