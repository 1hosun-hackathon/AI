from typing import Annotated, Literal, get_args

from pydantic import AfterValidator, BaseModel, Field

CriterionKey = Literal["thesis", "evidence", "structure", "expression", "originality"]
CRITERIA: tuple[str, ...] = get_args(CriterionKey)

# key: (이름, 설명). key는 API 계약이라 바꾸지 않고, 이름·설명만 리포트용 구조·논리 기준으로 쓴다(v3).
# 내용·결론·입장은 어느 항목에서도 평가하지 않는다.
CRITERIA_INFO: dict[str, tuple[str, str]] = {
    "thesis": ("목적·주제 설정", "다루는 문제와 범위, 글의 목적이 분명한가"),
    "evidence": ("근거와 출처", "주장마다 근거가 있고, 출처와 자기 해석이 구분되는가"),
    "structure": ("구성", "서론·본론·결론의 역할과 문단 구성이 분명한가"),
    "expression": ("표현", "문장이 정확하고 간결하며 용어가 일관된가"),
    "originality": ("논리 전개", "비약 없이 이어지고 결론이 본론에서 도출되는가"),
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
