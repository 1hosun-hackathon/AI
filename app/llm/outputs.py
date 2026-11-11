"""LLM 출력 전용 모델. API 응답 스키마(app/schemas)와 분리해 LLM에는 작은 필드만 시킨다.

필드 순서가 곧 생성 순서다: 요약 → 근거 → 점수 → 보완 방향.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import CriterionKey

Score = Literal[1, 2, 3, 4, 5]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SentenceRef(BaseModel):
    sentence_id: int
    reason: Text


class TextScoreOutput(BaseModel):
    """글 한 편을 항목 하나로 채점. 다른 글을 보지 않는다(두 글을 나란히 놓으면 한쪽으로 쏠림)."""

    summary: Text
    evidence: list[SentenceRef] = Field(max_length=3)
    score: Score


class TextScoreWithActionOutput(TextScoreOutput):
    """학습자 글 채점용. 보완 방향을 함께 받는다."""

    action: Text


class ItemComparison(BaseModel):
    key: CriterionKey
    comparison: Text


class CompareOutput(BaseModel):
    comparisons: list[ItemComparison]


class SummaryOutput(BaseModel):
    overall_report: Text
    strengths: list[Text] = Field(min_length=1, max_length=3)
    improvements: list[Text] = Field(min_length=1, max_length=3)
    questions: list[Text] = Field(min_length=2, max_length=4)


class FeedbackVerdict(BaseModel):
    index: int
    reason: Text  # 판정 전에 이유를 먼저 쓰게 해서 대충 찍는 판정을 줄인다
    verdict: Literal["ok", "stance_shift", "leading"]


class FeedbackCheckOutput(BaseModel):
    verdicts: list[FeedbackVerdict]


class ActionReview(BaseModel):
    key: CriterionKey
    reflected: Literal["yes", "partial", "no"]
    reason: Text


class ActionReviewOutput(BaseModel):
    reviews: list[ActionReview]
