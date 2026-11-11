from app.llm.outputs import SentenceRef
from app.schemas.analysis import Evidence


def resolve_evidence(refs: list[SentenceRef], sentences: list[str], source: str) -> list[Evidence]:
    """문장 번호 → 원문 문장. 범위를 벗어난 번호와 중복은 버린다."""
    out: list[Evidence] = []
    seen: set[int] = set()
    for ref in refs:
        if not 1 <= ref.sentence_id <= len(sentences) or ref.sentence_id in seen:
            continue
        seen.add(ref.sentence_id)
        out.append(Evidence(source=source, quote=sentences[ref.sentence_id - 1], reason=ref.reason))
    return out
