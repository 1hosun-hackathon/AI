"""대필 검사: 피드백이 참고 글을 베끼거나, 고쳐 쓴 예시 문장을 담고 있는지 본다."""

import re
from collections.abc import Iterable

from app.text.sentences import compact

# 따옴표 안이 문장 끝(~다, ~요, ~까)으로 끝날 때만 예시 문장으로 본다.
# 개념 인용('자기 조절')이 두 개 있을 때 그 사이 구간을 잘못 잡지 않게 하기 위함.
_QUOTED = re.compile(r"[\"“”'‘’「『]([^\"“”'‘’」』]{15,}?[다요까][.?!]?)[\"“”'‘’」』]")
_EXAMPLE_PATTERNS = [
    # "예: 첫 문장에 주장을 넣는다."처럼 뒤에 완성 문장이 올 때만. "(예: 설문 시기, 대상)" 같은 항목 나열은 허용.
    re.compile(r"예\s*[:：]\s*[^()\n,]{6,}?[다요][.\"”'’]?(\s|$)"),
    re.compile(r"예를\s*들(어|면)[^.?!]{0,40}(라고|처럼)\s*(쓰|써|작성|바꾸|바꿔|고치|고쳐)"),
    re.compile(r"(다음과|아래와)\s*같이\s*(고쳐|바꿔|수정|써|쓰)"),
    re.compile(r"(→|->)\s*\S"),
]


def _ngrams(text: str, n: int) -> set[str]:
    t = compact(text)
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def copied_ngrams(text: str, reference: str, n: int, exclude: Iterable[str] = ()) -> set[str]:
    """text와 reference가 공유하는 n-gram. exclude(주제·요구사항)에 나오는 n-gram은 뺀다."""
    shared = _ngrams(text, n) & _ngrams(reference, n)
    for ex in exclude:
        if ex:
            shared -= _ngrams(ex, n)
    return shared


def example_sentence_reasons(text: str, allowed_quote_sources: Iterable[str] = ()) -> list[str]:
    """완성 문장 예시로 보이는 패턴. 학습자 글을 그대로 인용한 따옴표는 허용한다."""
    reasons: list[str] = []
    allowed = [compact(s) for s in allowed_quote_sources if s]
    for m in _QUOTED.finditer(text):
        quoted = compact(m.group(1))
        if not any(quoted in a for a in allowed):
            reasons.append(f"따옴표로 감싼 문장: {m.group(1)[:30]}")
    for p in _EXAMPLE_PATTERNS:
        if p.search(text):
            reasons.append(f"예시 문장 패턴: {p.pattern}")
    return reasons


def ghostwriting_issues(
    text: str,
    ai_draft: str,
    *,
    n: int,
    exclude: Iterable[str] = (),
    allowed_quote_sources: Iterable[str] = (),
    max_shared: int = 0,
) -> list[str]:
    """max_shared: 허용할 겹침 n-gram 수. 종합 리포트처럼 AI 글을 언급할 수밖에 없는 필드는 짧은 겹침을 허용한다
    (n=12일 때 8개 ≈ 공백 제외 19자 연속 일치)."""
    issues = example_sentence_reasons(text, allowed_quote_sources)
    copied = copied_ngrams(text, ai_draft, n, exclude)
    if len(copied) > max_shared:
        issues.append(f"참고 글과 겹치는 구절 {len(copied)}개")
    return issues
