from typing import Annotated, Literal, get_args

from pydantic import AfterValidator, BaseModel, Field

CriterionKey = Literal["thesis", "evidence", "structure", "expression", "originality"]
CRITERIA: tuple[str, ...] = get_args(CriterionKey)

# key: (이름, 설명)
CRITERIA_INFO: dict[str, tuple[str, str]] = {
    "thesis": ("논지", "핵심 주장과 관점"),
    "evidence": ("근거", "자료와 사례의 활용"),
    "structure": ("구조", "글의 흐름과 구성"),
    "expression": ("표현", "문장의 명확성과 전달력"),
    "originality": ("독창성", "고유한 해석과 문제의식"),
}


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("빈 문자열은 허용되지 않습니다.")
    return value


NonBlank = Annotated[str, AfterValidator(_not_blank)]


class Requirements(BaseModel):
    length: str | None = Field(None, description='분량 문자열. 예: "800~1000자"')
    format: str | None = Field(None, description="글 형식. 예: 논설문")
    extra: str | None = None
    min_chars: int | None = Field(None, ge=1, description="추가 제안 필드(선택)")
    max_chars: int | None = Field(None, ge=1, description="추가 제안 필드(선택)")


class Meta(BaseModel):
    prompt_version: str
    model: str
