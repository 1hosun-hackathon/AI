from dataclasses import dataclass

import numpy as np

from app.llm.base import LLMProvider
from app.text.sentences import compact, split_sentences


@dataclass(frozen=True)
class Thresholds:
    ai_similar: float
    keep: float
    min_sentence_chars: int


@dataclass(frozen=True)
class LabeledSentence:
    text: str
    label: str  # kept | new | ai_similar
    sim_user: float
    sim_ai: float


def classify(sim_user: float, sim_ai: float, th: Thresholds) -> str:
    if sim_ai >= th.ai_similar and sim_ai > sim_user:
        return "ai_similar"
    if sim_user >= th.keep:
        return "kept"
    return "new"


def max_similarity(target: np.ndarray, others: np.ndarray) -> np.ndarray:
    """정규화된 임베딩 기준 target 각 행과 others 전체의 최대 코사인 유사도."""
    if others.shape[0] == 0:
        return np.zeros(target.shape[0], dtype=np.float32)
    return (target @ others.T).max(axis=1)


def dependency_ratio(sentences: list[LabeledSentence], min_chars: int) -> float:
    """ai_similar 문장의 글자 수(공백 제외) 비율. 짧은 문장은 집계에서 뺀다."""
    weights = [len(compact(s.text)) for s in sentences]
    counted = [(s, w) for s, w in zip(sentences, weights) if w >= min_chars]
    if not counted:  # 전부 짧은 문장이면 제외 규칙을 적용하지 않는다
        counted = list(zip(sentences, weights))
    total = sum(w for _, w in counted)
    if total == 0:
        return 0.0
    return sum(w for s, w in counted if s.label == "ai_similar") / total


async def label_sentences(
    llm: LLMProvider, user_draft: str, final_text: str, ai_draft: str, th: Thresholds
) -> list[LabeledSentence]:
    final_s = split_sentences(final_text)
    user_s = split_sentences(user_draft)
    ai_s = split_sentences(ai_draft)
    if not final_s:
        return []

    emb = await llm.embed(final_s + user_s + ai_s)  # 호출 1번
    f = emb[: len(final_s)]
    u = emb[len(final_s) : len(final_s) + len(user_s)]
    a = emb[len(final_s) + len(user_s) :]
    sim_u = max_similarity(f, u)
    sim_a = max_similarity(f, a)

    return [
        LabeledSentence(text, classify(float(su), float(sa), th), round(float(su), 4), round(float(sa), 4))
        for text, su, sa in zip(final_s, sim_u, sim_a)
    ]
