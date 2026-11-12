from pydantic import BaseModel

from app.schemas.common import Meta, NonBlank, Requirements


class ReferenceDraftRequest(BaseModel):
    topic: NonBlank
    requirements: Requirements = Requirements()
    references: list[str] = []  # 첨부파일에서 뽑은 참고 자료 (파일 하나당 한 덩어리)


class ReferenceDraftResponse(Meta):
    draft: str
    char_count: int
    warnings: list[str] = []
