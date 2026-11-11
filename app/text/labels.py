"""LLM 출력의 익명 라벨(A/B)을 사용자에게 보여줄 이름으로 바꾼다.

"글 A는" → "내 글은", "B가" → "AI 글이". 바뀐 이름이 모두 받침 있는 '글'로 끝나므로 조사도 맞춘다.
"""

import re

_LABEL = re.compile(r"(?:글\s*)?(?<![A-Za-z0-9])([AB])(?![A-Za-z0-9])(는|은|가|이|를|을|와|과)?")
_PARTICLE = {"는": "은", "은": "은", "가": "이", "이": "이", "를": "을", "을": "을", "와": "과", "과": "과"}


def relabel(text: str, names: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        particle = m.group(2)
        return names[m.group(1)] + (_PARTICLE[particle] if particle else "")

    return _LABEL.sub(sub, text)
