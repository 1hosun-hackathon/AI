from app.pipelines.reference_draft import clean_draft, length_range, size_targets
from app.schemas.common import Requirements
from app.text.diff import sentence_changes
from app.text.labels import relabel
from app.text.sentences import numbered, split_sentences

NAMES = {"A": "내 글", "B": "AI 글"}


def test_split_korean_sentences():
    text = "청소년의 스마트폰 사용은 제한해야 한다. 내 동생은 밤새 게임을 했다. 그래서 성적이 떨어졌다."
    assert split_sentences(text) == [
        "청소년의 스마트폰 사용은 제한해야 한다.",
        "내 동생은 밤새 게임을 했다.",
        "그래서 성적이 떨어졌다.",
    ]


def test_newline_is_sentence_boundary_and_numbering():
    sents = split_sentences("첫 문단 문장\n\n둘째 문단 문장")
    assert sents == ["첫 문단 문장", "둘째 문단 문장"]
    assert numbered(sents) == "(1) 첫 문단 문장\n(2) 둘째 문단 문장"


def test_sentence_changes():
    removed, added = sentence_changes(["가.", "나.", "다."], ["가.", "나2.", "다.", "라."])
    assert removed == ["나."]
    assert added == ["나2.", "라."]


def test_relabel_fixes_particles():
    assert relabel("글 A는 사례를, B는 통계를 쓴다.", NAMES) == "내 글은 사례를, AI 글은 통계를 쓴다."
    assert relabel("A가 더 낫고 글 B와 다르다.", NAMES) == "내 글이 더 낫고 AI 글과 다르다."
    assert relabel("AI 기술과 A4 용지", NAMES) == "AI 기술과 A4 용지"


def test_length_range():
    assert length_range(Requirements(length="800~1,000자")) == (800, 1000)
    assert length_range(Requirements(length="1000자 이내")) == (0, 1000)
    assert length_range(Requirements(length="500자 이상"))[0] == 500
    assert length_range(Requirements(length="자유")) is None
    assert length_range(Requirements(length="800~1000자", min_chars=700, max_chars=900)) == (700, 900)


def test_clean_draft_removes_markdown():
    assert clean_draft("# 제목\n\n**본문** 첫 문장.\n- 둘째 문장.") == "본문 첫 문장.\n둘째 문장."


def test_clean_draft_removes_plain_title_line():
    text = "청소년의 스마트폰 사용, 학교에서 제한해야 하는가\n\n디지털 시대에 스마트폰은 필수가 되었다."
    assert clean_draft(text) == "디지털 시대에 스마트폰은 필수가 되었다."
    # 문장 부호로 끝나는 첫 줄은 본문이므로 남긴다
    assert clean_draft("첫 문단이다.\n\n둘째 문단이다.") == "첫 문단이다.\n\n둘째 문단이다."


def test_size_targets():
    assert size_targets(500, 700) == (11, 3)
    assert size_targets(600, 800) == (13, 3)
