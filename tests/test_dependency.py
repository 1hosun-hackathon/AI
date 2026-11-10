import numpy as np

from app.embeddings.similarity import LabeledSentence, Thresholds, classify, dependency_ratio, max_similarity
from app.pipelines import dependency
from app.schemas.dependency import DependencyRequest

TH = Thresholds(ai_similar=0.80, keep=0.75, min_sentence_chars=8)


def test_classify_rules():
    assert classify(sim_user=0.3, sim_ai=0.9, th=TH) == "ai_similar"
    assert classify(sim_user=0.95, sim_ai=0.9, th=TH) == "kept"  # 내 초안에 더 가까우면 유지
    assert classify(sim_user=0.8, sim_ai=0.2, th=TH) == "kept"
    assert classify(sim_user=0.4, sim_ai=0.5, th=TH) == "new"


def test_max_similarity_handles_empty():
    target = np.eye(2, dtype=np.float32)
    assert max_similarity(target, np.zeros((0, 2), dtype=np.float32)).tolist() == [0.0, 0.0]


def test_ratio_is_char_weighted_and_skips_short():
    sents = [
        LabeledSentence("가" * 30, "ai_similar", 0, 1),
        LabeledSentence("나" * 10, "new", 0, 0),
        LabeledSentence("짧다.", "ai_similar", 0, 1),  # 8자 미만 → 집계 제외
    ]
    assert dependency_ratio(sents, 8) == 30 / 40


async def test_dependency_pipeline_labels(make_ctx):
    user = "청소년의 스마트폰 사용은 제한해야 한다. 내 동생은 밤새 게임을 하다가 성적이 떨어졌다."
    ai = "일괄 수거는 자기 조절 능력을 기를 기회를 빼앗는다. 통계청 조사에 따르면 과의존 위험군이 많다."
    final = (
        "청소년의 스마트폰 사용은 제한해야 한다. "
        "일괄 수거는 자기 조절 능력을 기를 기회를 빼앗는다. "
        "학교와 가정이 함께 사용 규칙을 정하는 방법을 고민했다."
    )
    res = await dependency.run(make_ctx(), DependencyRequest(user_draft=user, final_text=final, ai_draft=ai))
    assert [s.label for s in res.sentences] == ["kept", "ai_similar", "new"]
    assert 0 < res.ai_dependency_ratio < 1
    assert abs(res.self_composition_ratio + res.ai_dependency_ratio - 1) < 1e-6
    assert "0.80" in res.method.description
