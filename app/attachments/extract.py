"""첨부파일 → 문단 목록.

지원: PDF(pypdf), DOCX·PPTX·HWPX(압축 안의 XML), TXT·MD.
예전 형식(DOC·PPT·HWP)과 이미지는 글자를 뽑지 않는다(UnsupportedFormat).
"""

import io
import re
import zipfile
from pathlib import PurePath
from xml.etree import ElementTree as ET

SUPPORTED_EXT = {".pdf", ".docx", ".pptx", ".hwpx", ".txt", ".md"}

_MAX_PDF_PAGES = 100
_MAX_ZIP_ENTRY_BYTES = 30 * 1024 * 1024  # 압축을 푼 XML 하나의 최대 크기 (압축 폭탄 방지)
_MAX_ZIP_TOTAL_BYTES = 100 * 1024 * 1024
_WS = re.compile(r"[ \t 　]+")
_BLANK = re.compile(r"\n\s*\n")
_SLIDE = re.compile(r"ppt/slides/slide(\d+)\.xml$")
_SECTION = re.compile(r"Contents/section(\d+)\.xml$", re.I)


class UnsupportedFormat(Exception):
    """글자를 뽑지 않는 형식."""


class ExtractError(Exception):
    """지원 형식이지만 읽지 못함(손상, 암호 등)."""


def extract_paragraphs(filename: str, data: bytes, max_chars: int) -> list[str]:
    """파일 내용을 문단 목록으로 바꾼다. 앞에서부터 max_chars 글자까지만 담는다."""
    ext = PurePath(filename).suffix.lower()
    try:
        if ext in (".txt", ".md"):
            paras = _split_blocks(_decode(data))
        elif ext == ".pdf":
            paras = _pdf(data, max_chars)
        elif ext == ".docx":
            paras = _zip_xml(data, lambda n: n == "word/document.xml", None)
        elif ext == ".pptx":
            paras = _zip_xml(data, lambda n: bool(_SLIDE.match(n)), _SLIDE)
        elif ext == ".hwpx":
            paras = _zip_xml(data, lambda n: bool(_SECTION.match(n)), _SECTION)
        else:
            raise UnsupportedFormat(ext)
    except (UnsupportedFormat, ExtractError):
        raise
    except Exception as e:  # 손상된 파일은 라이브러리마다 다른 예외를 낸다
        raise ExtractError(f"{type(e).__name__}: {e}") from None
    return _limit(_dedupe(paras), max_chars)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\r", "")).strip()


def _split_blocks(text: str) -> list[str]:
    """빈 줄로 나눈 덩어리를 문단으로 본다. 덩어리 안의 줄바꿈은 공백으로 잇는다."""
    out = []
    for block in _BLANK.split(text.replace("\r\n", "\n")):
        lines = [_clean(line) for line in block.split("\n")]
        if para := " ".join(line for line in lines if line):
            out.append(para)
    return out


def _pdf(data: bytes, max_chars: int) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ExtractError("암호가 걸린 PDF")
    paras: list[str] = []
    total = 0
    for page in reader.pages[:_MAX_PDF_PAGES]:
        page_paras = _split_blocks(page.extract_text() or "")
        paras += page_paras
        total += sum(map(len, page_paras))
        if total >= max_chars:
            break
    return paras


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_paragraphs(root: ET.Element) -> list[str]:
    """이름이 p인 요소를 문단, t인 요소를 글자로 본다(DOCX w:, PPTX a:, HWPX hp: 공통).

    문단 안에 표·글상자 문단이 들어 있으면 따로 문단으로 꺼내 글자가 겹치지 않게 한다.
    """
    out: list[str] = []

    def collect(el: ET.Element, buf: list[str]) -> None:
        for child in el:
            name = _local(child.tag)
            if name == "p":
                paragraph(child)
            elif name == "t":
                buf.append("".join(child.itertext()))
            elif name in ("tab", "br", "lineBreak"):
                buf.append(" ")
            else:
                collect(child, buf)

    def paragraph(el: ET.Element) -> None:
        buf: list[str] = []
        collect(el, buf)
        if text := _clean("".join(buf)):
            out.append(text)

    if _local(root.tag) == "p":
        paragraph(root)
    else:
        collect(root, [])
    return out


def _zip_xml(data: bytes, want, order: re.Pattern | None) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if want(n)]
        if not names:
            raise ExtractError("본문 XML이 없음")
        if order:
            names.sort(key=lambda n: int(order.match(n).group(1)))
        paras: list[str] = []
        budget = _MAX_ZIP_TOTAL_BYTES
        for name in names:
            raw = _read_capped(zf, name, min(_MAX_ZIP_ENTRY_BYTES, budget))
            budget -= len(raw)
            paras += _xml_paragraphs(ET.fromstring(raw))
        return paras


def _read_capped(zf: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """압축을 풀면서 실제로 읽은 크기로 제한한다. 헤더의 file_size는 조작할 수 있어 믿지 않는다."""
    with zf.open(name) as f:
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ExtractError("압축을 푼 내용이 너무 큼")
    return raw


def _dedupe(paras: list[str]) -> list[str]:
    """같은 문단이 여러 번 나오면(글상자 대체 표현, 반복 머리글 등) 처음 것만 둔다. 짧은 문단은 그대로 둔다."""
    seen: set[str] = set()
    out = []
    for p in paras:
        if len(p) >= 20:
            if p in seen:
                continue
            seen.add(p)
        out.append(p)
    return out


def _limit(paras: list[str], max_chars: int) -> list[str]:
    out, total = [], 0
    for p in paras:
        if total + len(p) > max_chars:
            if rest := max_chars - total:
                out.append(p[:rest])
            break
        out.append(p)
        total += len(p)
    return out
