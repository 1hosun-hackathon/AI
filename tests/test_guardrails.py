from app.guardrails.citation import resolve_evidence
from app.guardrails.ghostwriting import copied_ngrams, example_sentence_reasons, ghostwriting_issues
from app.guardrails.questions import rule_check_question
from app.llm.outputs import EvidenceRef

AI_DRAFT = "스마트폰 일괄 수거는 청소년이 자기 조절 능력을 기를 기회를 빼앗는다는 점에서 바람직하지 않다."
TOPIC = "청소년의 스마트폰 사용 제한"


def test_detects_copied_phrase_from_ai_draft():
    text = "자기 조절 능력을 기를 기회를 빼앗는다는 관점을 참고해 보세요."
    assert copied_ngrams(text, AI_DRAFT, n=12)


def test_topic_phrases_are_not_counted():
    text = "청소년의 스마트폰 사용 제한에 대한 내 입장을 더 분명히 하세요."
    ai = "청소년의 스마트폰 사용 제한은 신중해야 한다."
    assert copied_ngrams(text, ai, n=12, exclude=[TOPIC]) == set()


def test_example_sentence_patterns():
    assert example_sentence_reasons('"스마트폰은 자율에 맡겨야 한다고 생각합니다"처럼 쓰세요.')
    assert example_sentence_reasons("예: 첫 문장에 주장을 넣는다.")
    assert example_sentence_reasons("다음과 같이 고쳐 보세요.")
    assert example_sentence_reasons("주장과 근거의 연결을 설명해 보세요.") == []


def test_quoting_learner_own_sentence_is_allowed():
    user = "내 동생은 밤새 게임을 하다가 성적이 떨어졌다."
    text = "'내 동생은 밤새 게임을 하다가 성적이 떨어졌다'는 하나의 사례에 그칩니다."
    assert ghostwriting_issues(text, AI_DRAFT, n=12, allowed_quote_sources=[user]) == []


def test_question_rules():
    assert rule_check_question("이 문제에서 가장 중요한 가치는 무엇이라고 생각하나요?") is None
    assert rule_check_question("규제가 2.5% 늘면 무엇이 달라질까?") is None
    assert rule_check_question("무엇이 중요한가.") == "물음표로 끝나지 않음"
    assert rule_check_question("좋은 질문이다. 왜 그런가?") == "한 문장이 아님"
    assert rule_check_question("통계를 더 넣어야 하지 않을까요?") == "답을 유도하는 어미"


def test_resolve_evidence_drops_out_of_range_and_duplicates():
    refs = [
        EvidenceRef(source="A", sentence_id=2, reason="r1"),
        EvidenceRef(source="A", sentence_id=2, reason="중복"),
        EvidenceRef(source="B", sentence_id=9, reason="범위 밖"),
        EvidenceRef(source="B", sentence_id=1, reason="r2"),
    ]
    sents = {"A": ["a1", "a2"], "B": ["b1"]}
    out = resolve_evidence(refs, sents, {"A": "user", "B": "ai"})
    assert [(e.source, e.quote) for e in out] == [("user", "a2"), ("ai", "b1")]
