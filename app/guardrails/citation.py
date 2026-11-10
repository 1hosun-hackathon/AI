from app.llm.outputs import EvidenceRef
from app.schemas.analysis import Evidence


def resolve_evidence(
    refs: list[EvidenceRef],
    sentences: dict[str, list[str]],
    label_to_source: dict[str, str],
) -> list[Evidence]:
    """문장 번호 → 원문 문장. 범위를 벗어난 번호와 중복은 버린다."""
    out: list[Evidence] = []
    seen: set[tuple[str, int]] = set()
    for ref in refs:
        sents = sentences.get(ref.source, [])
        if not 1 <= ref.sentence_id <= len(sents) or (ref.source, ref.sentence_id) in seen:
            continue
        seen.add((ref.source, ref.sentence_id))
        out.append(
            Evidence(source=label_to_source[ref.source], quote=sents[ref.sentence_id - 1], reason=ref.reason)
        )
    return out
