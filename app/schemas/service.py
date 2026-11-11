"""백엔드 API 명세(글적글적_API_명세서) 형식에 맞춘 요청·응답.

백엔드가 받은 값을 그대로 넘기고, 받은 결과를 그대로 저장·표시할 수 있게
필드 이름(camelCase)과 값 형식을 명세의 2-1, 3-2, 3-4, 3-5, 4-1, 4-2와 맞춘다.
내부 파이프라인은 기존 형식(app.schemas.analysis)을 쓰고, 여기서는 변환만 한다.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, WithJsonSchema

from app.schemas.common import NonBlank

Criterion = Literal["THESIS", "EVIDENCE", "STRUCTURE", "EXPRESSION", "ORIGINALITY"]
AnalysisStatus = Literal["PENDING", "GENERATING", "SUCCESS", "FAILED"]


class TaskInfo(BaseModel):
    """훈련 생성(2-1)의 과제 조건. 백엔드 training 값을 그대로 넣는다."""

    topic: NonBlank
    writingType: str | None = Field(None, description="글 형식. 예: 논설문")
    requirements: str | None = Field(None, description='과제 조건 문자열. 예: "800~1,000자, 근거 2개 이상"')


class Content(BaseModel):
    content: NonBlank


# 2-1 훈련 생성 → AI 작성 글


class AiWritingRequest(TaskInfo):
    pass


class AiWritingResponse(BaseModel):
    content: str = Field(description="4-2 aiWriting.content로 저장할 AI 작성 글")
    charCount: int
    warnings: list[str] = []
    promptVersion: str
    model: str


# 3-2 초안 제출, 3-4 다시 검사하기 → 비교 분석


class EvidenceQuote(BaseModel):
    source: Literal["user", "ai"]
    quote: str
    reason: str


class AnalysisItem(BaseModel):
    criterion: Criterion
    label: str
    description: str
    userSummary: str
    aiSummary: str
    comparison: str
    reflectPoint: str | None = Field(None, description="보완 방향. 대필 검사를 통과하지 못하면 null")
    userScore: int = Field(ge=1, le=5, description="화면에는 표시하지 않음. 대시보드 집계·재검사에 사용")
    aiScore: int = Field(ge=1, le=5)
    better: Literal["user", "ai", "tie"]
    evidence: list[EvidenceQuote] = []


class Question(BaseModel):
    seqNo: int
    content: str


class ReflectionReview(BaseModel):
    criterion: Criterion
    reflectPoint: str
    reflected: Literal["yes", "partial", "no"]
    reason: str


class AnalysisReport(BaseModel):
    """4-2 비교 분석 결과의 AI 부분. 다시 검사할 때 previousResult로 그대로 돌려준다."""

    seqNo: int
    overallSummary: str | None = Field(None, description="종합 리포트. 검사를 통과하지 못하면 null")
    strengths: str = Field(description="강점. 여러 개면 줄바꿈으로 구분")
    improvements: str = Field(description="보완할 점. 여러 개면 줄바꿈으로 구분")
    items: list[AnalysisItem] = Field(description="THESIS, EVIDENCE, STRUCTURE, EXPRESSION, ORIGINALITY 순서")
    questions: list[Question]
    reflectionReviews: list[ReflectionReview] = Field([], description="다시 검사(seqNo≥1)일 때 지난 reflectPoint 반영 여부")
    scoreDelta: dict[Criterion, int] = Field({}, description="다시 검사일 때 직전 회차 대비 userScore 변화")
    partial: bool = Field(False, description="일부 항목·필드가 빠졌으면 true. 사유는 warnings")
    warnings: list[str] = []
    promptVersion: str
    model: str


class AnalysisRequest(TaskInfo):
    seqNo: int = Field(0, ge=0, description="0이면 초안 제출(3-2), 1 이상이면 다시 검사하기(3-4)")
    myWriting: Content = Field(description="이번에 제출한 글")
    aiWriting: Content
    baseline: Content | None = Field(None, description="seqNo≥1일 때 필수. 최초 초안(seqNo 0)")
    previousResult: AnalysisReport | None = Field(None, description="seqNo≥1일 때 필수. 직전 회차 분석 결과 그대로")


class AnalysisAccepted(BaseModel):
    jobId: str
    status: AnalysisStatus = "PENDING"


class AnalysisJob(BaseModel):
    """4-1 분석 상태. SUCCESS면 result, FAILED면 error가 채워진다."""

    jobId: str
    status: AnalysisStatus
    result: Annotated[
        dict[str, Any] | None,
        WithJsonSchema({"anyOf": [{"$ref": "#/components/schemas/AnalysisReport"}, {"type": "null"}]}),
    ] = None
    error: dict[str, Any] | None = Field(None, description='{"code", "message", "retryable"}')


# 3-5 훈련 완료 → 자기 사고 비율


class RatioRequest(BaseModel):
    draft: Content = Field(description="최초 초안(seqNo 0)")
    finalWriting: Content = Field(description="훈련 완료 시 확정한 최종 글")
    aiWriting: Content


class RatioSentence(BaseModel):
    text: str
    label: Literal["kept", "new", "ai_similar"]
    simUser: float
    simAi: float


class RatioResponse(BaseModel):
    selfThoughtRatio: float = Field(description="0~100, 소수 첫째 자리")
    aiDependencyRatio: float = Field(description="0~100, 소수 첫째 자리. selfThoughtRatio와 합이 100")
    sentences: list[RatioSentence]
    method: str = Field(description="산정 기준 설명")
    promptVersion: str
    model: str
