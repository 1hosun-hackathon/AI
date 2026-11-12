"""첨부파일 글자 추출 (app.attachments.extract)."""

import io
import zipfile

import pytest

from app.attachments import extract
from app.attachments.extract import ExtractError, UnsupportedFormat, extract_paragraphs

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
HP = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'


def _zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in entries.items():
            zf.writestr(name, text)
    return buf.getvalue()


def _pdf(lines: list[str]) -> bytes:
    """글자가 든 최소 PDF (Helvetica, 영문)."""
    stream = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({t}) Tj 0 -20 Td" for t in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_txt_splits_on_blank_lines_and_reads_cp949():
    data = "첫 문단 첫 줄\n이어지는 줄\n\n\n둘째 문단".encode("cp949")
    assert extract_paragraphs("메모.txt", data, 1000) == ["첫 문단 첫 줄 이어지는 줄", "둘째 문단"]


def test_docx_paragraphs_and_table_cells_do_not_merge():
    doc = (
        f"<w:document {W}><w:body>"
        "<w:p><w:r><w:t>탄소 중립은 </w:t></w:r><w:r><w:t>2050년 목표다.</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>표 칸 하나</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:body></w:document>"
    )
    paras = extract_paragraphs("자료.docx", _zip({"word/document.xml": doc}), 1000)
    assert paras == ["탄소 중립은 2050년 목표다.", "표 칸 하나"]


def test_pptx_follows_slide_number_not_name_order():
    def slide(text):
        return f"<p:sld {A} xmlns:p='p'><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>"

    data = _zip({"ppt/slides/slide10.xml": slide("열 번째"), "ppt/slides/slide2.xml": slide("두 번째")})
    assert extract_paragraphs("발표.pptx", data, 1000) == ["두 번째", "열 번째"]


def test_hwpx_sections():
    sec = f"<hs:sec xmlns:hs='s' {HP}><hp:p><hp:run><hp:t>한글 문서 본문</hp:t></hp:run></hp:p></hs:sec>"
    assert extract_paragraphs("보고서.hwpx", _zip({"Contents/section0.xml": sec}), 1000) == ["한글 문서 본문"]


def test_pdf_text():
    paras = extract_paragraphs("report.pdf", _pdf(["Carbon tax cut emissions", "by 27 percent"]), 1000)
    text = " ".join(paras)
    assert "Carbon tax cut emissions" in text and "27 percent" in text


def test_limit_cuts_at_max_chars_and_dedupes_long_repeats():
    header = "반복되는 머리글은 한 번만 남겨야 한다"  # 20자 이상
    data = f"{header}\n\n본문 하나\n\n{header}\n\n본문 둘".encode()
    assert extract_paragraphs("a.md", data, 1000) == [header, "본문 하나", "본문 둘"]
    assert extract_paragraphs("a.md", data, 25) == [header, "본문 하나"[: 25 - len(header)]]


@pytest.mark.parametrize("name", ["옛문서.hwp", "옛발표.ppt", "옛문서.doc", "사진.png"])
def test_legacy_and_image_formats_are_unsupported(name):
    with pytest.raises(UnsupportedFormat):
        extract_paragraphs(name, b"anything", 1000)


@pytest.mark.parametrize("name", ["broken.pdf", "broken.docx", "broken.hwpx"])
def test_broken_files_raise_extract_error(name):
    with pytest.raises(ExtractError):
        extract_paragraphs(name, b"not a real file", 1000)


def test_docx_without_body_xml_is_extract_error():
    with pytest.raises(ExtractError):
        extract_paragraphs("빈.docx", _zip({"other.xml": "<x/>"}), 1000)


def test_zip_size_cap_uses_bytes_actually_read(monkeypatch):
    # 압축률이 높은 큰 XML: 헤더 값과 상관없이 실제로 푼 크기로 막아야 한다.
    monkeypatch.setattr(extract, "_MAX_ZIP_ENTRY_BYTES", 1000)
    doc = f"<w:document {W}><w:body><w:p><w:r><w:t>{'가' * 5000}</w:t></w:r></w:p></w:body></w:document>"
    with pytest.raises(ExtractError, match="너무 큼"):
        extract_paragraphs("폭탄.docx", _zip({"word/document.xml": doc}), 1000)
