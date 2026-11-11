from app.guardrails.citation import resolve_evidence
from app.guardrails.ghostwriting import copied_ngrams, example_sentence_reasons, ghostwriting_issues
from app.guardrails.neutrality import content_shift_reasons, one_sided_question
from app.guardrails.questions import normalize_question, rule_check_question
from app.llm.outputs import SentenceRef

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


def test_example_listing_is_not_example_sentence():
    # "예:" 뒤에 항목만 나열하면 허용 (v3 평가 오탐)
    assert example_sentence_reasons("자료를 얻은 방법(예: 설문 시기, 대상, 인원)을 밝혀 보세요.") == []


def test_report_allows_short_overlap_and_shared_vocabulary():
    ai = "다회용 컵 대여 및 회수 시스템을 구축하는 것이 필수적이다. 캠퍼스 내 다회용 컵 보관 및 세척 시설을 확충해야 한다."
    user = "학생회관에 다회용 컵 무료 대여함을 설치했다."
    # 학습자 글에도 있는 표현은 겹침으로 세지 않는다
    assert copied_ngrams("두 글 모두 다회용 컵 무료 대여함을 다룬다.", ai + " 다회용 컵 무료 대여함", n=12, exclude=[user]) == set()
    # 짧은 언급은 리포트에서 허용, 긴 문장 복사는 잡는다
    short = "AI 글은 다회용 컵 대여 및 회수를 다룬다."
    assert ghostwriting_issues(short, ai, n=12, max_shared=8) == []
    long_copy = "AI 글처럼 캠퍼스 내 다회용 컵 보관 및 세척 시설을 확충해야 한다고 쓰세요."
    assert ghostwriting_issues(long_copy, ai, n=12, max_shared=8)


def test_concept_quotes_are_not_example_sentences():
    text = "내 글은 '결과'에 초점을 맞추었다면, AI 참고 글은 '과정의 성찰'을 강조한다."
    assert example_sentence_reasons(text) == []


def test_quoting_learner_own_sentence_is_allowed():
    user = "내 동생은 밤새 게임을 하다가 성적이 떨어졌다."
    text = "'내 동생은 밤새 게임을 하다가 성적이 떨어졌다'는 하나의 사례에 그칩니다."
    assert ghostwriting_issues(text, AI_DRAFT, n=12, allowed_quote_sources=[user]) == []


def test_content_shift_rules():
    # v2 평가에서 LLM 판정을 통과했던 실제 출력
    leaked = "AI 참고 글이 제시하는 '학습 및 사고 심화 도구'로서의 AI 활용 가능성에 대해 자신의 입장을 재검토해 볼 필요가 있습니다."
    assert content_shift_reasons(leaked)
    assert content_shift_reasons("두 입장을 절충하는 방향으로 결론을 바꿔 보세요.")
    assert content_shift_reasons("AI 글처럼 결론을 구성해 보세요.")
    # 구성·근거·논리 보완은 통과
    assert content_shift_reasons("결론이 본론의 어느 근거에서 나왔는지 연결을 보강해 보세요.") == []
    assert content_shift_reasons("예상되는 반론을 한 문단으로 다뤄 보세요.") == []


def test_one_sided_question():
    assert one_sided_question("습관 기록이 삶의 질 향상에 미치는 긍정적인 영향은 무엇일까?")
    assert one_sided_question("이 제도의 긍정적 측면과 부정적 측면은 무엇인가요?") is None
    assert one_sided_question("이 결론은 본론의 어느 근거에서 나왔나요?") is None


def test_question_rules():
    assert rule_check_question("이 문제에서 가장 중요한 가치는 무엇이라고 생각하나요?") is None
    assert rule_check_question("규제가 2.5% 늘면 무엇이 달라질까?") is None
    assert rule_check_question("무엇이 중요한가.") == "물음표로 끝나지 않음"
    assert rule_check_question("좋은 질문이다. 왜 그런가?") == "한 문장이 아님"
    assert rule_check_question("통계를 더 넣어야 하지 않을까요?") == "답을 유도하는 어미"


def test_normalize_question_adds_missing_question_mark():
    assert normalize_question("자료와 해석을 어떻게 구분했나요.") == "자료와 해석을 어떻게 구분했나요?"
    assert normalize_question("이 결론은 어느 근거에서 나왔는가") == "이 결론은 어느 근거에서 나왔는가?"
    # 명령문은 질문으로 바꾸지 않는다
    assert normalize_question("근거를 점검해 보세요.") == "근거를 점검해 보세요."
    assert rule_check_question(normalize_question("근거를 점검해 보세요.")) == "물음표로 끝나지 않음"


def test_resolve_evidence_drops_out_of_range_and_duplicates():
    refs = [
        SentenceRef(sentence_id=2, reason="r1"),
        SentenceRef(sentence_id=2, reason="중복"),
        SentenceRef(sentence_id=9, reason="범위 밖"),
        SentenceRef(sentence_id=1, reason="r2"),
    ]
    out = resolve_evidence(refs, ["s1", "s2"], "user")
    assert [(e.source, e.quote, e.reason) for e in out] == [("user", "s2", "r1"), ("user", "s1", "r2")]
