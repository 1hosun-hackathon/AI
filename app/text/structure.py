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
