# MCP tra cứu văn bản pháp luật

MCP server riêng để Claude tra cứu văn bản pháp luật Việt Nam từ kho dữ liệu của chị: tìm văn bản, xem mục lục, trích nguyên văn Điều/Khoản/Điểm, kiểm tra hiệu lực và văn bản liên quan.

Bản đặc tả: <https://claude.ai/artifact/Un2rHJ1M63b6XZveyEvpVa>

## Tình trạng hiện tại (bản 0.1)

| Phần | Trạng thái |
| --- | --- |
| Kho dữ liệu SQLite, tìm kiếm có dấu và không dấu | Xong, đã kiểm thử |
| Tách cấu trúc Chương/Mục/Điều/Khoản/Điểm/Phụ lục, giữ nguyên văn | Xong, đã kiểm thử trên văn bản mẫu |
| 7 chức năng MCP | Xong, đã kiểm thử |
| Nhập văn bản từ tệp .docx, .txt, .html, .pdf | Xong |
| Thu thập tự động từ vbpl.vn | Chưa có: cần chạy lệnh khảo sát (bước 4) để em viết |

## Cài đặt trên Windows

Các lệnh dưới đây gõ trong **PowerShell** (bấm phím Windows, gõ "PowerShell", Enter).

### 1. Cài Python

Tải Python 3.12 trở lên tại <https://www.python.org/downloads/windows/>. Khi cài, **đánh dấu ô "Add python.exe to PATH"**. Kiểm tra:

```powershell
py --version
```

### 2. Lấy mã nguồn

Cách dễ nhất: mở <https://github.com/Stork108/mcp-phap-luat>, bấm **Code > Download ZIP**, giải nén vào ví dụ `C:\mcp-phap-luat`.

(Nếu máy có Git: `git clone https://github.com/Stork108/mcp-phap-luat C:\mcp-phap-luat`.)

### 3. Cài đặt

```powershell
cd C:\mcp-phap-luat
py -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\phapluat -h
```

Lệnh cuối hiện danh sách lệnh là cài thành công.

### 4. Khảo sát vbpl.vn (để em viết bộ thu thập tự động)

```powershell
.venv\Scripts\phapluat khao-sat-vbpl
```

Lệnh tải khoảng 15 trang, mỗi trang cách nhau 4 giây, tôn trọng robots.txt, rồi lưu vào thư mục `C:\mcp-phap-luat\khao-sat-vbpl`. Chị nén thư mục đó (chuột phải > Send to > Compressed (zipped) folder) và gửi lại trong thread.

Bước 2 của khảo sát (đọc sơ đồ trang `sitemap.xml` và 4 trang chi tiết văn bản; không gọi `/api/` và `/Pages/` vì robots.txt của vbpl.vn không cho phép):

```powershell
.venv\Scripts\phapluat khao-sat-vbpl --buoc 2
```

Kết quả nằm trong thư mục `khao-sat-vbpl-2`.

### Cập nhật mã nguồn khi có bản mới

Tải lại ZIP và giải nén **đè lên** thư mục cũ (`C:\mcp-phap-luat`), chọn "Replace" khi Windows hỏi. Không cần cài lại.

### 5. Nhập thử một văn bản

Tải bản Word (.docx) của một văn bản từ vbpl.vn, rồi:

```powershell
.venv\Scripts\phapluat nhap "C:\Users\<tên>\Downloads\Luat-Doanh-nghiep.docx" --tinh-trang "Còn hiệu lực" --nguon vbpl.vn --url "https://vbpl.vn/..."
.venv\Scripts\phapluat thong-ke
```

Số ký hiệu, cơ quan, trích yếu, ngày ban hành được tự đọc từ phần đầu văn bản và được gắn cảnh báo "cần đối chiếu nguồn". Có thể ghi đè bằng `--so-ky-hieu`, `--co-quan`, `--trich-yeu`, `--ngay-ban-hanh`, `--ngay-hieu-luc`, `--ngay-het-hieu-luc`, `--linh-vuc`. Văn bản địa phương thêm `--tinh-goc "Bình Dương" --tinh-hien-nay "TP. Hồ Chí Minh" --pham-vi "địa bàn tỉnh Bình Dương trước sắp xếp"`.

Nhập nhiều văn bản một lúc: lập bảng CSV có cột `tep` (tên tệp) và các cột `so_ky_hieu, co_quan_ban_hanh, trich_yeu, tinh_trang_nguon, ...`, rồi chạy `phapluat nhap-danh-muc danh-muc.csv`.

Ghi quan hệ sửa đổi, thay thế (để có cảnh báo khi trích dẫn). Cú pháp: `phapluat quan-he <văn bản tác động> <loại> <văn bản bị tác động> --vi-tri-dich "<vị trí>"`, ví dụ với hai văn bản mẫu kiểm thử:

```powershell
.venv\Scripts\phapluat quan-he 1000/2099/NĐ-CP sua_doi 999/2099/NĐ-CP --vi-tri-dich "khoản 2 Điều 3"
```

### 6. Kết nối với Claude Code

```powershell
claude mcp add phap-luat --scope user -e PHAPLUAT_DB=C:\mcp-phap-luat\data\phapluat.db -- C:\mcp-phap-luat\.venv\Scripts\phapluat.exe serve
```

Mở lại Claude Code, gõ `/mcp` để thấy `phap-luat` đã kết nối.

## Các chức năng

| Chức năng | Dùng để |
| --- | --- |
| `tim_van_ban` | Tìm theo từ khóa hoặc số ký hiệu; lọc theo loại, cơ quan, tỉnh, lĩnh vực, ngày |
| `xem_muc_luc` | Thông tin văn bản và mục lục |
| `lay_toan_van` | Toàn văn, chia trang |
| `tra_cuu_tuan_thu` | Các Điều liên quan nhất tới một tình huống, chỉ trong văn bản đang có hiệu lực |
| `trich_dieu_khoan` | Nguyên văn Điều/Khoản/Điểm, kèm cảnh báo nếu đã bị sửa đổi, thay thế, bãi bỏ |
| `kiem_tra_hieu_luc` | Tình trạng hiệu lực của một hoặc nhiều văn bản |
| `van_ban_lien_quan` | Văn bản căn cứ, hướng dẫn, sửa đổi, thay thế, hợp nhất |

## Chạy trên cloud (giai đoạn sau)

```bash
export PHAPLUAT_TOKEN="<chuỗi ngẫu nhiên dài ít nhất 24 ký tự>"
phapluat serve --http --port 8000
```

Máy chủ chỉ trả lời yêu cầu có header `Authorization: Bearer <token>`. Cách đặt sau HTTPS và cách xác thực khi thêm vào Claude dưới dạng connector tùy chỉnh sẽ được hoàn thiện ở giai đoạn đưa lên cloud.

## Dành cho phát triển

```bash
pip install -e ".[dev]"
pytest
```

Văn bản trong `tests/fixtures` là văn bản mẫu hư cấu (số hiệu năm 2099), chỉ dùng để kiểm thử.
