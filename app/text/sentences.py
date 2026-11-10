import re
from functools import lru_cache

_LINES = re.compile(r"\n+")
_WS = re.compile(r"\s+")


@lru_cache(maxsize=1)
def _kiwi():
    from kiwipiepy import Kiwi

    return Kiwi()


def split_sentences(text: str) -> list[str]:
    """한국어 문장 분리. 줄바꿈은 항상 문장 경계로 본다."""
    out: list[str] = []
    for line in _LINES.split(text.strip()):
        line = line.strip()
        if not line:
            continue
        out.extend(s.text.strip() for s in _kiwi().split_into_sents(line) if s.text.strip())
    return out


def numbered(sentences: list[str]) -> str:
    return "\n".join(f"({i}) {s}" for i, s in enumerate(sentences, 1))


def compact(text: str) -> str:
    """공백을 모두 지운 문자열 (글자 수·n-gram 비교용)."""
    return _WS.sub("", text)
