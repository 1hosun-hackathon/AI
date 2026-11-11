from app.text.sentences import numbered_paragraphs, split_paragraphs, split_sentences
from app.text.structure import is_heading, observe

GOOD = (
    "이 리포트는 아르바이트가 학업에 미치는 영향을 살펴보는 것을 목적으로 한다. 자료는 학과 설문을 사용하였다.\n\n"
    "설문에서 주 15시간 이상 일하는 학생의 학점이 낮았다. 이 집단은 과제를 몰아서 했다.\n\n"
    "이 차이는 학습 시간이 줄어들기 때문으로 해석할 수 있다. 다만 한 학과만 조사했다.\n\n"
    "정리하면, 근무 시간이 학업에 영향을 준다. 따라서 학업과 병행하기 쉬운 일자리가 필요하다."
)
# 같은 문장, 순서만 섞고 문단을 없앤 글
SCRAMBLED = (
    "반면 이 집단은 과제를 몰아서 했다. 정리하면, 근무 시간이 학업에 영향을 준다. "
    "이 리포트는 아르바이트가 학업에 미치는 영향을 살펴보는 것을 목적으로 한다. 다만 한 학과만 조사했다. "
    "설문에서 주 15시간 이상 일하는 학생의 학점이 낮았다. 자료는 학과 설문을 사용하였다."
)


def test_paragraph_numbering_keeps_global_sentence_ids():
    paras = split_paragraphs("첫 문장이다. 둘째 문장이다.\n\n셋째 문장이다.")
    assert paras == [["첫 문장이다.", "둘째 문장이다."], ["셋째 문장이다."]]
    assert numbered_paragraphs(paras) == "[문단 1]\n(1) 첫 문장이다.\n(2) 둘째 문장이다.\n\n[문단 2]\n(3) 셋째 문장이다."
    # split_sentences의 순서 = 문장 번호 순서 (인용 문장 번호와 일치해야 함)
    assert split_sentences("첫 문장이다. 둘째 문장이다.\n\n셋째 문장이다.")[2] == "셋째 문장이다."


def test_observe_well_structured_report():
    facts = observe(split_paragraphs(GOOD))
    assert "문단 수: 4개" in facts
    assert "1번째 문장 (첫 문단)" in facts
    assert "마지막 문단" in facts
    # 문단 첫 문장의 "이 차이는"은 앞 문단을 받는 정상 연결이라 잡지 않는다
    assert "받는 말" not in facts
    assert "한 덩어리" not in facts


def test_observe_scrambled_report():
    facts = observe(split_paragraphs(SCRAMBLED))
    assert "문단 수: 1개" in facts
    assert "3/6번째 문장" in facts
    assert "전체 6문장 중 2번째" in facts
    assert "글의 첫 문장이 앞 내용을 받는 말" in facts
    assert "한 덩어리로 썼다" in facts


def test_headings_are_not_counted_as_paragraphs():
    text = "서론: 문제 제기\n\n이 보고서는 컵 사용을 줄이는 방안을 다룬다.\n\n결론\n\n정리하면, 대여함이 필요하다."
    paras = split_paragraphs(text)
    assert is_heading(paras[0]) and not is_heading(paras[1])
    facts = observe(paras)
    assert "문단 수: 2개" in facts
    assert "마지막 문단" in facts


# ---------------------------------------------------------------- 근거와 출처, 논리 전개 관찰값
from app.text.structure import observe_flow, observe_sources, source_kind  # noqa: E402


def test_source_kinds():
    assert source_kind("운영팀 통계에 따르면 사용량이 약 8% 줄었다.") == "source"
    assert source_kind("자료로는 학과 설문 결과를 사용하였다.") == "source"
    # 누가·언제 조사했는지 없는 출처
    assert source_kind("연구에 따르면 대면 강의가 더 효과적이라고 한다.") == "vague"
    assert source_kind("많은 학생들이 성적이 떨어졌다고 한다.") == "vague"
    assert source_kind("효과적일 수 있다는 연구 결과들이 존재한다.") == "vague"
    # "본 보고서는"은 출처가 아니다
    assert source_kind("본 보고서는 구체적인 저감 방안을 제시하고자 한다.") is None


def test_observe_sources_counts():
    facts = observe_sources(split_paragraphs(GOOD))
    # 설문 결과(2, 3번째)와 조사 범위를 밝힌 문장(6번째)
    assert "밝힌 문장('설문', '통계', '~에 따르면' 등): 3개" in facts
    assert "수치(숫자)가 들어간 문장: 1개" in facts
    facts = observe_sources(split_paragraphs("연구에 따르면 효과가 있다고 한다. 그래서 늘려야 한다."))
    assert "0개" in facts and "막연한 출처" in facts


def test_observe_flow_detects_conclusion_before_data():
    facts = observe_flow(split_paragraphs(GOOD))
    assert "전체 8문장 중 7번째, 8번째" in facts
    assert "새로 나오는 수치·자료 문장: 없음" in facts
    # 결론을 먼저 쓰고 자료를 뒤에 붙인 글
    late = "따라서 근무 시간을 줄여야 한다. 설문에서 주 15시간 이상 일하는 학생의 학점이 낮았다."
    assert "다시 나온다: 2번째 문장" in observe_flow(split_paragraphs(late))


def test_heading_numbers_are_not_data():
    text = "본론 1: 실행 방안\n\n따라서 대여함을 늘려야 한다.\n\n본론 2: 지원 방안\n\n세척 시설을 확충해야 한다."
    facts = observe_flow(split_paragraphs(text))
    assert "새로 나오는 수치·자료 문장: 없음" in facts
    assert "수치(숫자)가 들어간 문장: 0개" in observe_sources(split_paragraphs(text))
