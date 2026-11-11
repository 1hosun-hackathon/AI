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
