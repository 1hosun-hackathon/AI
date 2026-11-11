"""내용 중립 검사: 피드백이 결론·관점을 바꾸라고 권하거나, 한쪽 결론을 전제하는지 규칙으로 먼저 거른다.

LLM 판정(feedback_check)은 소형 모델이라 놓치는 경우가 있어서(v2 평가: "자신의 입장을 재검토해 볼 필요"가 통과),
명백한 표현은 여기서 확실히 막는다.
"""

import re

# 보완 방향·보완할 점: 결론·관점 변경 권유, AI 글을 따르라는 권유
_SHIFT_PATTERNS = [
    (re.compile(r"(입장|결론|관점|주장)\S{0,3}\s*(을|를)?\s*(재검토|재고|다시\s*생각|바꾸|바꿔|수정|전환|철회)"), "결론·관점 변경 권유"),
    (re.compile(r"(절충|중간\s*입장|양쪽\s*입장을\s*(모두\s*)?(수용|받아들))"), "절충 권유"),
    (re.compile(r"(AI|참고)\s*글\S{0,2}\s*(이|가)?\s*(제시하는|말하는|주장하는)\s*\S*\s*(관점|입장|결론|가능성)"), "AI 글의 관점을 따르라는 권유"),
    (re.compile(r"(AI|참고)\s*글(처럼|과\s*같이|의\s*(관점|입장|결론)(을|를)\s*(반영|수용|참고))"), "AI 글을 따르라는 권유"),
    (re.compile(r"(관점|입장)(을|를)\s*(받아들|수용)"), "다른 관점을 받아들이라는 권유"),
]

# 질문: 한쪽 평가를 전제 ("긍정적 영향은 무엇일까요?"). "긍정적·부정적 측면"처럼 양쪽을 다 물으면 허용.
_ONE_SIDED = re.compile(r"(긍정적|부정적|좋은|나쁜)\s*(인\s*)?(영향|효과|측면|점|결과)")
_BOTH_SIDES = re.compile(r"긍정.{0,15}부정|부정.{0,15}긍정|장점.{0,15}단점|단점.{0,15}장점")


def content_shift_reasons(text: str) -> list[str]:
    return [reason for pattern, reason in _SHIFT_PATTERNS if pattern.search(text)]


def one_sided_question(question: str) -> str | None:
    if _ONE_SIDED.search(question) and not _BOTH_SIDES.search(question):
        return "한쪽 평가를 전제한 질문"
    return None
