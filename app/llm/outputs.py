"""LLM 출력 전용 모델. API 응답 스키마(app/schemas)와 분리해 LLM에는 작은 필드만 시킨다.

필드 순서가 곧 생성 순서다: 요약 → 근거 → 비교 → 점수 → 보완 방향.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import CriterionKey

Score = Literal[1, 2, 3, 4, 5]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EvidenceRef(BaseModel):
    source: Literal["A", "B"]
    sentence_id: int
    reason: Text


class ItemEvalOutput(BaseModel):
    """항목 하나 평가. 학습자/AI 구분 없이 A/B로만 본다(블라인드)."""

    a_summary: Text
    b_summary: Text
    evidence: list[EvidenceRef] = Field(max_length=6)
    comparison: Text
    a_score: Score
    b_score: Score
    better: Literal["A", "B", "tie"]
    a_action: Text  # 글 A가 이 항목에서 보완할 방향
    b_action: Text


class SummaryOutput(BaseModel):
    overall_report: Text
    strengths: list[Text] = Field(min_length=1, max_length=3)
    improvements: list[Text] = Field(min_length=1, max_length=3)
    questions: list[Text] = Field(min_length=2, max_length=4)


class QuestionVerdict(BaseModel):
    index: int
    verdict: Literal["open", "leading"]


class QuestionCheckOutput(BaseModel):
    verdicts: list[QuestionVerdict]


class ActionReview(BaseModel):
    key: CriterionKey
    reflected: Literal["yes", "partial", "no"]
    reason: Text


class ActionReviewOutput(BaseModel):
    reviews: list[ActionReview]
