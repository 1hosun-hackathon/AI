import re

_ENDINGS = re.compile(r"[.?!。](?=\s)")  # "2.5%" 같은 소수점은 문장 끝이 아님
_LEADING = re.compile(r"(해야\s*하지\s*않|하는\s*게\s*좋지\s*않|아닐까요|않을까요|않나요|않습니까)\s*\?$")


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
