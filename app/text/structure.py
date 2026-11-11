"""구조 관찰값: 서버가 직접 센 사실을 채점 프롬프트에 넣는다.

소형 모델은 문장 순서가 뒤섞여도 내용만 보고 "서론에서 목적을 제시한다"고 판단한다(v3 1차 평가: 문장을 뒤섞은 글의
구성·논리 점수가 원래 글과 거의 같았음). 문단 수, 목적 문장과 결론 표지의 위치처럼 세기 쉬운 사실을 알려 주면
루브릭("문단 구분이 거의 없다 → 2점")을 적용하기 쉬워진다. 내용은 보지 않으므로 중립성에 영향이 없다.
"""

import re

_PURPOSE = re.compile(r"(목적|살펴보|알아보|분석하고자|다루고자|밝히고자|하고자\s*한다|보고서는|리포트는)")
_CONCLUSION = re.compile(r"^(정리하면|결론적으로|요약하면|종합하면|이상을\s*정리하면|결국)")
_BACKREF = re.compile(r"^(반면|그러나|하지만|또한|그래서|따라서|즉|이\s*(차이|결과|점)|그\s*결과)")


def _fmt(positions: list[int]) -> str:
    return ", ".join(f"{p}번째" for p in positions)


_SENT_END = re.compile(r"[.?!。다요]$")


def is_heading(para: list[str]) -> bool:
    """'서론: 문제 제기' 같은 소제목 줄. 문단 수에서 뺀다."""
    return len(para) == 1 and len(para[0]) < 40 and not _SENT_END.search(para[0].rstrip("\"'”’)"))


def observe(paragraphs: list[list[str]]) -> str:
    sentences = [s for para in paragraphs for s in para]
    total = len(sentences)
    if total == 0:
        return ""
    # 소제목은 바로 뒤 문단에 속한 것으로 보고 문단 번호를 매긴다.
    para_of: list[int] = []
    n_body = 0
    for para in paragraphs:
        if is_heading(para):
            para_of.extend([n_body + 1] * len(para))
        else:
            n_body += 1
            para_of.extend([n_body] * len(para))
    n_para = max(para_of)

    lines = [f"- 문단 수: {n_para}개 (문장 {total}개)"]

    purpose = [i for i, s in enumerate(sentences, 1) if _PURPOSE.search(s)]
    if purpose:
        where = "첫 문단" if para_of[purpose[0] - 1] == 1 and n_para > 1 else f"{purpose[0]}/{total}번째 문장"
        lines.append(f"- 글의 목적을 밝히는 문장: {_fmt(purpose[:2])} 문장 ({where})")
    else:
        lines.append("- 글의 목적을 밝히는 문장: 찾지 못함")

    conclusion = [i for i, s in enumerate(sentences, 1) if _CONCLUSION.search(s)]
    if conclusion:
        in_last = all(para_of[i - 1] == n_para for i in conclusion) and n_para > 1
        where = "마지막 문단" if in_last else f"전체 {total}문장 중 {_fmt(conclusion)}"
        lines.append(f"- 결론을 여는 말('정리하면', '결론적으로' 등)로 시작하는 문장: {where}")
    else:
        lines.append("- 결론을 여는 말('정리하면', '결론적으로' 등)로 시작하는 문장: 없음")

    # 글의 첫 문장이 앞 내용을 받는 말로 시작하면 받을 내용이 없다. (문단 첫 문장은 앞 문단을 받을 수 있어 정상)
    if _BACKREF.search(sentences[0]):
        lines.append("- 글의 첫 문장이 앞 내용을 받는 말('반면', '이 차이는' 등)로 시작한다")
    if n_para == 1 and total >= 6:
        lines.append("- 문단을 나누지 않고 한 덩어리로 썼다")
    return "\n".join(lines)


# ---------------------------------------------------------------- 논리 전개: 결론·제안 문장과 자료 문장의 순서

_CLOSING_START = re.compile(r"^(따라서|정리하면|결론적으로|요약하면|종합하면|이상을\s*정리하면|결국)")
_CLOSING_END = re.compile(r"(필요가\s*있다|해야\s*한다|바람직하다)[.\s]*$")
_DIGIT = re.compile(r"\d")

# ---------------------------------------------------------------- 근거와 출처: 출처 표지

_SOURCE = re.compile(
    r"(에\s*따르면|설문|통계|면담|인터뷰|조사(했|한|를|에서|\s*결과)|보고서(에서|에\s*따르면)"
    r"|자료(로는|에서|를\s*보면)|강의\s*자료|문헌|논문|기사|발표한|공개한|출처)"
)
# 누가·언제 조사했는지 없는 출처 ("연구에 따르면", "많은 학생들이 ~라고 한다")
_VAGUE = re.compile(
    r"(연구(에\s*따르면|\s*결과(들)?(가|이|에\s*따르면|도)|들은)|전문가들|많은\s*(사람|학생)들?(이|은)|(라고|다고)\s*한다)"
)


def is_closing(sentence: str) -> bool:
    return bool(_CLOSING_START.search(sentence) or _CLOSING_END.search(sentence))


def source_kind(sentence: str) -> str | None:
    """'vague'(막연한 출처) | 'source'(출처·자료 제시) | None. 숫자가 있으면 막연하다고 보지 않는다."""
    if _VAGUE.search(sentence) and not _DIGIT.search(sentence):
        return "vague"
    if _SOURCE.search(sentence):
        return "source"
    return None


def _is_data(sentence: str) -> bool:
    return bool(_DIGIT.search(sentence)) or source_kind(sentence) == "source"


def _body_sentences(paragraphs: list[list[str]]) -> tuple[list[str], set[int]]:
    """전체 문장(번호는 프롬프트와 같게 소제목 포함)과 소제목 문장 번호. '본론 1:'의 숫자를 수치로 세지 않기 위해."""
    sentences = [s for para in paragraphs for s in para]
    headings: set[int] = set()
    i = 0
    for para in paragraphs:
        if is_heading(para):
            headings.add(i + 1)
        i += len(para)
    return sentences, headings


def observe_flow(paragraphs: list[list[str]]) -> str:
    """결론·제안 문장 뒤에 수치·자료 문장이 다시 나오면 결론이 근거보다 먼저 나온 것이다."""
    sentences, headings = _body_sentences(paragraphs)
    total = len(sentences)
    closing = [i for i, s in enumerate(sentences, 1) if i not in headings and is_closing(s)]
    if not closing:
        return "- 결론·제안 문장('따라서', '정리하면'으로 시작하거나 '필요가 있다', '해야 한다'로 끝남): 없음"
    lines = [f"- 결론·제안 문장('따라서', '정리하면'으로 시작하거나 '필요가 있다', '해야 한다'로 끝남): 전체 {total}문장 중 {_fmt(closing[:4])}"]
    after = [
        i
        for i in range(closing[0] + 1, total + 1)
        if i not in closing and i not in headings and _is_data(sentences[i - 1])
    ]
    if after:
        lines.append(f"- 첫 결론·제안 문장 뒤에 수치나 자료를 제시하는 문장이 다시 나온다: {_fmt(after[:4])} 문장")
    else:
        lines.append("- 첫 결론·제안 문장 뒤에 새로 나오는 수치·자료 문장: 없음")
    return "\n".join(lines)


_EXPLICIT_CONCLUSION = re.compile(r"^(정리하면|결론적으로|요약하면|종합하면|이상을\s*정리하면)")
SCORE_CAP = 3


def score_cap(key: str, paragraphs: list[list[str]]) -> str | None:
    """오탐이 거의 없는 관찰일 때만 점수 상한(3점)을 건다. 상한을 건 사유를 돌려준다.

    모델은 루브릭에 같은 규칙을 적어도 뒤섞은 글 3편 중 2편에 논리 전개 4점을 줬다(v4 평가).
    '따라서'·'~해야 한다'는 본론 중간에도 흔해서 상한 조건에서 뺀다. 두 글에 똑같이 적용한다.
    """
    sentences, headings = _body_sentences(paragraphs)
    body = [(i, s) for i, s in enumerate(sentences, 1) if i not in headings]
    if not body:
        return None
    if key == "evidence":
        if not any(source_kind(s) == "source" for _, s in body):
            return "출처나 자료를 얻은 방법을 밝힌 문장이 없다"
        return None
    if key == "originality":
        if _BACKREF.search(body[0][1]):
            return "글의 첫 문장이 앞 내용을 받는 말로 시작한다"
        concl = next((i for i, s in body if _EXPLICIT_CONCLUSION.search(s)), None)
        if concl is not None and any(i > concl and _is_data(s) for i, s in body):
            return "결론을 여는 문장 뒤에 수치나 자료가 다시 나와 결론이 근거보다 먼저 나온다"
    return None


def observe_sources(paragraphs: list[list[str]]) -> str:
    sentences, headings = _body_sentences(paragraphs)
    if not sentences:
        return ""
    kinds = [None if i in headings else source_kind(s) for i, s in enumerate(sentences, 1)]
    src = [i for i, k in enumerate(kinds, 1) if k == "source"]
    vague = [i for i, k in enumerate(kinds, 1) if k == "vague"]
    nums = [i for i, s in enumerate(sentences, 1) if i not in headings and _DIGIT.search(s)]
    total = len(sentences)
    lines = [
        f"- 출처나 자료를 얻은 방법을 밝힌 문장('설문', '통계', '~에 따르면' 등): {len(src)}개"
        + (f" ({_fmt(src[:5])})" if src else "")
        + f" / 전체 {total}문장",
        f"- 수치(숫자)가 들어간 문장: {len(nums)}개",
    ]
    if vague:
        lines.append(
            f"- 누가·언제 조사했는지 없는 막연한 출처('연구에 따르면', '~라고 한다' 등): {len(vague)}개 ({_fmt(vague[:5])})"
        )
    return "\n".join(lines)
