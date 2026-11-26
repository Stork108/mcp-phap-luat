"""Đọc chữ từ tệp văn bản (.txt, .docx, .html, .pdf) mà không sửa nội dung."""

from __future__ import annotations

from pathlib import Path


class UnsupportedFile(Exception):
    pass


def _docx_text(path: Path) -> str:
    from docx import Document  # python-docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    out: list[str] = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            table = Table(child, doc)
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    t = cell.text.strip()
                    if not cells or cells[-1] != t:  # ô gộp lặp lại
                        cells.append(t)
                out.append(" | ".join(cells))
    return "\n".join(out)


def _html_text(path: Path) -> str:
    from bs4 import BeautifulSoup

    raw = path.read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def read_text(path: str | Path) -> tuple[str, list[str]]:
    """Trả về (chữ, cảnh báo)."""
    p = Path(path)
    ext = p.suffix.lower()
    warnings: list[str] = []
    if ext in (".txt", ".md"):
        text = p.read_text(encoding="utf-8-sig")
    elif ext == ".docx":
        text = _docx_text(p)
    elif ext in (".html", ".htm"):
        text = _html_text(p)
    elif ext == ".pdf":
        text = _pdf_text(p)
        warnings.append(
            "Chữ được đọc từ PDF có thể sai dòng hoặc thiếu dấu; cần đối chiếu bản gốc trước khi trích dẫn."
        )
        if len(text.strip()) < 200:
            warnings.append("PDF gần như không có lớp chữ (có thể là bản scan), chưa đọc được nội dung.")
    elif ext == ".doc":
        raise UnsupportedFile("Tệp .doc (Word cũ) chưa hỗ trợ: mở bằng Word và lưu lại dạng .docx.")
    else:
        raise UnsupportedFile(f"Chưa hỗ trợ định dạng {ext}")
    return text, warnings
