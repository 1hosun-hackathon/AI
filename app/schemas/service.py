"""노션 API 명세(글적글적_API_명세서)의 경로·필드에 맞춘 요청·응답.

경로와 응답 필드 이름은 명세의 2-1, 3-2, 3-4, 3-5, 4-1, 4-2, 4-4와 같다.
AI 서버는 훈련·글 버전을 저장하지 않으므로, 명세 요청 본문에 AI가 쓸 값(주제, AI 작성 글 등)과
백엔드가 발급한 analysisId를 더해 받는다. 내부 파이프라인은 app.schemas.analysis 형식을 쓰고 여기서는 변환만 한다.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import NonBlank

Criterion = Literal["THESIS", "EVIDENCE", "STRUCTURE", "EXPRESSION", "ORIGINALITY"]
AnalysisStatus = Literal["PENDING", "GENERATING", "SUCCESS", "FAILED"]

# 명세 4-2 예시의 화면 이름. 평가 기준 자체는 app.schemas.common.CRITERIA_INFO를 따른다.
LABELS: dict[str, tuple[str, str]] = {
    "THESIS": ("논지", "핵심 주장과 관점"),
    "EVIDENCE": ("근거", "자료와 사례의 활용"),
    "STRUCTURE": ("구조", "글의 흐름과 구성"),
    "EXPRESSION": ("표현", "문장의 명확성과 전달력"),
    "ORIGINALITY": ("독창성", "고유한 해석과 문제의식"),
}


class Task(BaseModel):
    """훈련 생성(2-1) 때 받은 과제 조건. training 값을 그대로 넣는다."""

    topic: NonBlank
    writingType: str | None = Field(None, description="예: 논설문")
    requirements: str | None = Field(None, description='예: "800~1,000자, 근거 2개 이상"')


class Writing(BaseModel):
    versionId: int | None = None
    content: str


class AiWriting(BaseModel):
    content: str


# 2-1 훈련 생성


class TrainingCreateRequest(Task):
    """multipart/form-data의 request 파트(JSON). files 파트는 받기만 하고 AI 작성 글에는 쓰지 않는다."""

    trainingId: int | None = None
    timerMinutes: int | None = None


class Attachment(BaseModel):
    fileName: str
    fileSize: int


class TrainingCreateResponse(BaseModel):
    trainingId: int | None
    aiWriting: AiWriting = Field(description="4-2 aiWriting으로 저장할 AI 작성 글")
    attachments: list[Attachment] = Field([], description="받은 첨부파일 (AI 작성 글에는 반영하지 않음)")
    charCount: int
    warnings: list[str] = []
    promptVersion: str
    model: str


# 3-2 초안 제출, 3-4 다시 검사하기


class DraftSubmitRequest(Task):
    analysisId: int = Field(description="백엔드가 만든 comparison_analysis ID")
    versionId: int | None = None
    content: str = Field(description="제출한 글")
    aiWriting: AiWriting | None = Field(
        None, description="AI 작성 글. 없거나 비어 있으면(2-1 생성 실패) 분석 전에 먼저 생성하고 4-2 aiWriting으로 돌려준다"
    )


class RevisionSubmitRequest(DraftSubmitRequest):
    seqNo: int = Field(ge=1)
    baseline: Writing = Field(description="최초 초안(seqNo 0)")
    previousResult: "ComparisonAnalysis" = Field(description="직전 회차 4-2 결과(GET /api/v1/analyses/{analysisId} 응답) 그대로")


class SubmitAccepted(BaseModel):
    versionId: int | None
    seqNo: int
    analysisId: int
    status: Literal["ANALYZING"] = "ANALYZING"


# 4-1 분석 상태, 4-4 재시도


class AnalysisStatusResponse(BaseModel):
    analysisId: int
    status: AnalysisStatus
    trainingStatus: Literal["ANALYZING", "COMPARED"]
    error: dict | None = Field(None, description='FAILED일 때 {"code", "message", "retryable"}')


class RetryAccepted(BaseModel):
    analysisId: int
    status: Literal["PENDING"] = "PENDING"


# 4-2 비교 분석 결과


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


class CriterionScore(BaseModel):
    """명세 4-2 화면 응답에는 넣지 않는 점수. 백엔드가 저장해 대시보드 집계와 다시 검사에 쓴다."""

    criterion: Criterion
    userScore: int = Field(ge=1, le=5)
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


class ComparisonAnalysis(BaseModel):
    analysisId: int
    trainingId: int | None
    seqNo: int
    createdAt: str
    myWriting: Writing
    aiWriting: AiWriting
    baseline: Writing | None = Field(None, description="재검사(seqNo≥1)일 때만 최초 초안")
    overallSummary: str | None
    strengths: str = Field(description="여러 개면 줄바꿈으로 구분")
    improvements: str = Field(description="여러 개면 줄바꿈으로 구분")
    items: list[AnalysisItem] = Field(description="THESIS, EVIDENCE, STRUCTURE, EXPRESSION, ORIGINALITY 순서")
    questions: list[Question]
    # 명세에 없는 추가 필드. 화면 응답에서는 빼고 백엔드가 저장한다.
    scores: list[CriterionScore] = Field(description="항목별 점수 (items와 같은 순서)")
    reflectionReviews: list[ReflectionReview] = []
    scoreDelta: dict[Criterion, int] = {}
    partial: bool = False
    warnings: list[str] = []
    promptVersion: str
    model: str


RevisionSubmitRequest.model_rebuild()


# 3-5 훈련 완료


class CompleteRequest(BaseModel):
    content: str = Field(description="최종 글")
    finalVersionId: int | None = None
    draft: Writing = Field(description="최초 초안(seqNo 0)")
    aiWriting: AiWriting


class RatioSentence(BaseModel):
    text: str
    label: Literal["kept", "new", "ai_similar"]
    simUser: float
    simAi: float


class CompleteResponse(BaseModel):
    trainingId: int
    status: Literal["COMPLETED"] = "COMPLETED"
    finalVersionId: int | None
    completedAt: str
    selfThoughtRatio: float = Field(description="0~100, 소수 첫째 자리")
    aiDependencyRatio: float = Field(description="0~100. selfThoughtRatio와 합이 100")
    sentences: list[RatioSentence]
    method: str
    promptVersion: str
    model: str


# 4-3 회차별 분석 목록


class AnalysisSummary(BaseModel):
    analysisId: int
    seqNo: int
    status: AnalysisStatus
    createdAt: str
