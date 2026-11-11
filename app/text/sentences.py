import re
from functools import lru_cache

_LINES = re.compile(r"\n+")
_WS = re.compile(r"\s+")


@lru_cache(maxsize=1)
def _kiwi():
    from kiwipiepy import Kiwi

    return Kiwi()


def _split_line(line: str) -> list[str]:
    line = line.strip()
    if not line:
        return []
    return [s.text.strip() for s in _kiwi().split_into_sents(line) if s.text.strip()]


def split_paragraphs(text: str) -> list[list[str]]:
    """문단(줄바꿈 단위)별 문장 목록. 줄바꿈은 항상 문단 경계로 본다."""
    return [sents for line in _LINES.split(text.strip()) if (sents := _split_line(line))]


def split_sentences(text: str) -> list[str]:
    """한국어 문장 분리. 번호는 이 순서(문단을 이어 붙인 순서)를 따른다."""
    return [s for para in split_paragraphs(text) for s in para]


def numbered(sentences: list[str]) -> str:
    return "\n".join(f"({i}) {s}" for i, s in enumerate(sentences, 1))


def numbered_paragraphs(paragraphs: list[list[str]]) -> str:
    """문단 경계가 보이도록 번호를 매긴다. 문장 번호는 글 전체에서 이어진다.

    문장만 한 줄씩 나열하면 문단 구분이 사라져, 문단을 나눈 글과 한 덩어리 글이 모델에게 똑같이 보인다(v3 1차 평가).
    """
    lines: list[str] = []
    n = 0
    for p, sents in enumerate(paragraphs, 1):
        if lines:
            lines.append("")
        lines.append(f"[문단 {p}]")
        for s in sents:
            n += 1
            lines.append(f"({n}) {s}")
    return "\n".join(lines)


def compact(text: str) -> str:
    """공백을 모두 지운 문자열 (글자 수·n-gram 비교용)."""
    return _WS.sub("", text)
