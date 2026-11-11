from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import CriterionKey, Meta, NonBlank, Requirements


class Evidence(BaseModel):
    source: Literal["user", "ai"]
    quote: str = Field(description="원문 그대로의 문장 (서버가 문장 번호로 채움)")
    reason: str


class ItemResult(BaseModel):
    key: CriterionKey
    user_score: int = Field(ge=1, le=5)
    ai_score: int = Field(ge=1, le=5)
    user_summary: str
    ai_summary: str
    comparison: str
    evidence: list[Evidence] = []
    better: Literal["user", "ai", "tie"]
    action_item: str | None = Field(None, description="가드레일을 통과하지 못하면 null")


class AnalysisResult(Meta):
    status: Literal["done", "partial", "failed"]
    items: list[ItemResult]
    overall_report: str | None = None
    strengths: list[str] = []
    improvements: list[str] = []
    questions: list[str] = []
    failed_items: list[CriterionKey] = []
    warnings: list[str] = []


class ActionItemReview(BaseModel):
    key: CriterionKey
    action_item: str
    reflected: Literal["yes", "partial", "no"]
    reason: str


class ReanalysisResult(AnalysisResult):
    action_item_review: list[ActionItemReview] = []
    score_delta: dict[CriterionKey, int] = {}


class AnalyzeRequest(BaseModel):
    topic: NonBlank
    requirements: Requirements = Requirements()
    user_draft: NonBlank
    ai_draft: NonBlank


class ReanalyzeRequest(BaseModel):
    topic: NonBlank
    requirements: Requirements = Requirements()
    original_draft: NonBlank
    current_draft: NonBlank
    ai_draft: NonBlank
    previous_result: AnalysisResult
    round: int = Field(ge=2)
