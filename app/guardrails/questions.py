import re

_ENDINGS = re.compile(r"[.?!。](?=\s)")  # "2.5%" 같은 소수점은 문장 끝이 아님
_LEADING = re.compile(r"(해야\s*하지\s*않|하는\s*게\s*좋지\s*않|아닐까요|않을까요|않나요|않습니까)\s*\?$")


_INTERROGATIVE = re.compile(r"(까요?|나요|가요|는가|은가|인가|던가|습니까|니)$")


def normalize_question(question: str) -> str:
    """의문형 어미로 끝났는데 물음표만 빠진 질문("~할까요.")에 물음표를 붙인다(v4 평가: 질문 3개가 모두 빠져 partial).
    "~해 보세요." 같은 명령문은 질문이 아니므로 그대로 둔다."""
    q = question.strip()
    body = q.rstrip(".。 ")
    if not q.endswith("?") and _INTERROGATIVE.search(body):
        return body + "?"
    return q


def rule_check_question(question: str) -> str | None:
    """규칙 검사. 통과하면 None, 아니면 사유."""
    q = question.strip()
    if not q.endswith("?"):
        return "물음표로 끝나지 않음"
    if len(_ENDINGS.findall(q[:-1])) > 0:
        return "한 문장이 아님"
    if _LEADING.search(q):
        return "답을 유도하는 어미"
    return None
