from pydantic import BaseModel

from app.schemas.common import Meta, NonBlank, Requirements


class ReferenceDraftRequest(BaseModel):
    topic: NonBlank
    requirements: Requirements = Requirements()


class ReferenceDraftResponse(Meta):
    draft: str
    char_count: int
    warnings: list[str] = []
