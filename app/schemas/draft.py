from pydantic import BaseModel, Field

from app.schemas.common import Meta, NonBlank, Requirements


class ReferenceDraftRequest(BaseModel):
    topic: NonBlank
    requirements: Requirements = Requirements()
    references: list[str] = Field(
        [], max_length=5, description="참고 자료 글 (자료 하나당 한 덩어리). 합계 ATTACHMENT_MAX_CHARS자까지만 쓰고 나머지는 자른다"
    )


class ReferenceDraftResponse(Meta):
    draft: str
    char_count: int
    warnings: list[str] = []
