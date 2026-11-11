from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Meta, NonBlank


class DependencyRequest(BaseModel):
    user_draft: NonBlank
    final_text: NonBlank
    ai_draft: NonBlank


class SentenceLabel(BaseModel):
    text: str
    label: Literal["kept", "new", "ai_similar"]
    sim_user: float
    sim_ai: float


class DependencyMethod(BaseModel):
    embedding_model: str
    ai_similar_threshold: float
    keep_threshold: float
    weighting: Literal["chars"] = "chars"
    description: str


class DependencyResponse(Meta):
    self_composition_ratio: float
    ai_dependency_ratio: float
    sentences: list[SentenceLabel]
    method: DependencyMethod
