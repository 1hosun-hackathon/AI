"""노션 API 명세 경로(/api/v1/...)의 AI 부분. 기존 파이프라인을 쓰고 요청·응답만 변환한다.

백엔드가 같은 경로·ID(trainingId, analysisId)로 이 서버를 호출하면 된다.
분석 결과는 서버 메모리에 JOB_TTL_SEC 동안만 남으므로, SUCCESS가 되면 백엔드가 4-2 결과를 받아 저장한다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

from app.api.deps import check_lengths, get_ctx, get_jobs
from app.api.routes import _submit
from app.errors import AppError
from app.jobs.store import JobFactory, JobStore
from app.pipelines import analyze, dependency, reanalyze, reference_draft
from app.pipelines.context import Ctx
from app.schemas import analysis as core
from app.schemas.common import Requirements
from app.schemas.dependency import DependencyRequest
from app.schemas.draft import ReferenceDraftRequest
from app.schemas.service import (
    LABELS,
    AiWriting,
    AnalysisItem,
    ComparisonAnalysis,
    AnalysisStatusResponse,
    CompleteRequest,
    CompleteResponse,
    DraftSubmitRequest,
    EvidenceQuote,
    Question,
    RatioSentence,
    ReflectionReview,
    RetryAccepted,
    RevisionSubmitRequest,
    SubmitAccepted,
    Task,
    TrainingCreateRequest,
    TrainingCreateResponse,
    Writing,
)

router = APIRouter(prefix="/api/v1", tags=["노션 API 명세"])

_KST = timezone(timedelta(hours=9))
_STATUS = {"queued": "PENDING", "running": "GENERATING", "done": "SUCCESS", "failed": "FAILED"}


@dataclass
class _Analysis:
    job_id: str
    kind: str
    factory: JobFactory


def _registry(request: Request) -> dict[int, _Analysis]:
    if not hasattr(request.app.state, "analyses"):
        request.app.state.analyses = {}
    return request.app.state.analyses


def _requirements(task: Task) -> Requirements:
    # "800~1,000자, 근거 2개 이상"에서 분량을 해석하고, 나머지 조건도 그대로 모델에 전달된다.
    return Requirements(format=task.writingType, length=task.requirements)


def _require_content(*texts: str) -> None:
    if any(not t.strip() for t in texts):
        raise AppError("EMPTY_CONTENT")


def to_result(res: core.AnalysisResult, meta: dict) -> ComparisonAnalysis:
    def criterion(key: str) -> str:
        return key.upper()

    return ComparisonAnalysis(
        **meta,
        overallSummary=res.overall_report,
        strengths="\n".join(res.strengths),
        improvements="\n".join(res.improvements),
        items=[
            AnalysisItem(
                criterion=criterion(it.key),
                label=LABELS[criterion(it.key)][0],
                description=LABELS[criterion(it.key)][1],
                userSummary=it.user_summary,
                aiSummary=it.ai_summary,
                comparison=it.comparison,
                reflectPoint=it.action_item,
                userScore=it.user_score,
                aiScore=it.ai_score,
                better=it.better,
                evidence=[EvidenceQuote(**e.model_dump()) for e in it.evidence],
            )
            for it in res.items
        ],
        questions=[Question(seqNo=i, content=q) for i, q in enumerate(res.questions, 1)],
        reflectionReviews=[
            ReflectionReview(criterion=criterion(r.key), reflectPoint=r.action_item, reflected=r.reflected, reason=r.reason)
            for r in getattr(res, "action_item_review", [])
        ],
        scoreDelta={criterion(k): v for k, v in getattr(res, "score_delta", {}).items()},
        partial=res.status != "done",
        warnings=res.warnings,
        promptVersion=res.prompt_version,
        model=res.model,
    )


def from_result(prev: ComparisonAnalysis) -> core.AnalysisResult:
    """previousResult를 재분석 파이프라인 형식으로 되돌린다."""
    return core.AnalysisResult(
        status="partial" if prev.partial else "done",
        items=[
            core.ItemResult(
                key=it.criterion.lower(),
                user_score=it.userScore,
                ai_score=it.aiScore,
                user_summary=it.userSummary,
                ai_summary=it.aiSummary,
                comparison=it.comparison,
                evidence=[core.Evidence(**e.model_dump()) for e in it.evidence],
                better=it.better,
                action_item=it.reflectPoint,
            )
            for it in prev.items
        ],
        overall_report=prev.overallSummary,
        strengths=[s for s in prev.strengths.split("\n") if s],
        improvements=[s for s in prev.improvements.split("\n") if s],
        questions=[q.content for q in prev.questions],
        warnings=prev.warnings,
        prompt_version=prev.promptVersion,
        model=prev.model,
    )


def _start(request: Request, jobs: JobStore, analysis_id: int, kind: str, factory: JobFactory) -> None:
    created = _submit(jobs, kind, factory)
    _registry(request)[analysis_id] = _Analysis(job_id=created.job_id, kind=kind, factory=factory)


def _lookup(request: Request, jobs: JobStore, analysis_id: int):
    entry = _registry(request).get(analysis_id)
    job = jobs.get(entry.job_id) if entry else None
    if job is None:
        _registry(request).pop(analysis_id, None)
        raise AppError("ANALYSIS_NOT_FOUND")
    return entry, job


@router.post("/trainings", status_code=201, response_model=TrainingCreateResponse)
async def create_training(req: TrainingCreateRequest, ctx: Ctx = Depends(get_ctx)):
    """2-1 훈련 생성: 과제 조건만으로 AI 작성 글을 만든다(동기, 수십 초). 4-4에서 AI 글 생성이 실패했을 때도 다시 호출한다."""
    res = await reference_draft.run(ctx, ReferenceDraftRequest(topic=req.topic, requirements=_requirements(req)))
    return TrainingCreateResponse(
        trainingId=req.trainingId,
        aiWriting=AiWriting(content=res.draft),
        charCount=res.char_count,
        warnings=res.warnings,
        promptVersion=res.prompt_version,
        model=res.model,
    )


@router.post("/trainings/{trainingId}/draft", status_code=202, response_model=SubmitAccepted)
async def submit_draft(
    trainingId: int, req: DraftSubmitRequest, request: Request, ctx: Ctx = Depends(get_ctx), jobs: JobStore = Depends(get_jobs)
):
    """3-2 초안 제출: 초안과 AI 작성 글을 비교 분석한다(비동기). 4-1로 상태를 확인한다."""
    _require_content(req.content, req.aiWriting.content)
    check_lengths(ctx.settings, req.content, req.aiWriting.content)
    core_req = core.AnalyzeRequest(
        topic=req.topic, requirements=_requirements(req), user_draft=req.content, ai_draft=req.aiWriting.content
    )
    meta = dict(
        analysisId=req.analysisId,
        trainingId=trainingId,
        seqNo=0,
        createdAt=datetime.now(_KST).isoformat(timespec="seconds"),
        myWriting=Writing(versionId=req.versionId, content=req.content),
        aiWriting=req.aiWriting,
    )

    async def job():
        return to_result(await analyze.run(ctx, core_req), meta)

    _start(request, jobs, req.analysisId, "analyze", job)
    return SubmitAccepted(versionId=req.versionId, seqNo=0, analysisId=req.analysisId)


@router.post("/trainings/{trainingId}/revisions", status_code=202, response_model=SubmitAccepted)
async def submit_revision(
    trainingId: int,
    req: RevisionSubmitRequest,
    request: Request,
    ctx: Ctx = Depends(get_ctx),
    jobs: JobStore = Depends(get_jobs),
):
    """3-4 다시 검사하기: 수정본을 다시 분석하고 지난 보완 방향(reflectPoint) 반영 여부를 본다(비동기)."""
    _require_content(req.content, req.aiWriting.content, req.baseline.content)
    check_lengths(ctx.settings, req.baseline.content, req.content, req.aiWriting.content)
    if req.content.strip() == req.previousResult.myWriting.content.strip():
        raise AppError("NO_CHANGES")
    core_req = core.ReanalyzeRequest(
        topic=req.topic,
        requirements=_requirements(req),
        original_draft=req.baseline.content,
        current_draft=req.content,
        ai_draft=req.aiWriting.content,
        previous_result=from_result(req.previousResult),
        round=req.seqNo + 1,
    )
    meta = dict(
        analysisId=req.analysisId,
        trainingId=trainingId,
        seqNo=req.seqNo,
        createdAt=datetime.now(_KST).isoformat(timespec="seconds"),
        myWriting=Writing(versionId=req.versionId, content=req.content),
        aiWriting=req.aiWriting,
        baseline=req.baseline,
    )

    async def job():
        return to_result(await reanalyze.run(ctx, core_req), meta)

    _start(request, jobs, req.analysisId, "reanalyze", job)
    return SubmitAccepted(versionId=req.versionId, seqNo=req.seqNo, analysisId=req.analysisId)


@router.post("/trainings/{trainingId}/complete", response_model=CompleteResponse)
async def complete_training(trainingId: int, req: CompleteRequest, ctx: Ctx = Depends(get_ctx)):
    """3-5 훈련 완료: 최종 글의 자기 사고 비율·AI 의존도(%)를 계산한다. LLM 미사용, 동기."""
    _require_content(req.content, req.draft.content, req.aiWriting.content)
    check_lengths(ctx.settings, req.draft.content, req.content, req.aiWriting.content)
    res = await dependency.run(
        ctx, DependencyRequest(user_draft=req.draft.content, final_text=req.content, ai_draft=req.aiWriting.content)
    )
    ai = round(res.ai_dependency_ratio * 100, 1)
    return CompleteResponse(
        trainingId=trainingId,
        selfThoughtRatio=round(100 - ai, 1),
        aiDependencyRatio=ai,
        sentences=[RatioSentence(text=s.text, label=s.label, simUser=s.sim_user, simAi=s.sim_ai) for s in res.sentences],
        method=res.method.description,
        promptVersion=res.prompt_version,
        model=res.model,
    )


@router.get("/analyses/{analysisId}/status", response_model=AnalysisStatusResponse)
async def analysis_status(analysisId: int, request: Request, jobs: JobStore = Depends(get_jobs)):
    """4-1 분석 상태. 2초 간격 폴링."""
    _, job = _lookup(request, jobs, analysisId)
    status = _STATUS[job.state]
    return AnalysisStatusResponse(
        analysisId=analysisId,
        status=status,
        trainingStatus="COMPARED" if status == "SUCCESS" else "ANALYZING",
        error=job.error,
    )


@router.get("/analyses/{analysisId}", response_model=ComparisonAnalysis)
async def analysis_result(analysisId: int, request: Request, jobs: JobStore = Depends(get_jobs)):
    """4-2 비교 분석 결과. SUCCESS 전에는 409 ANALYSIS_NOT_READY."""
    _, job = _lookup(request, jobs, analysisId)
    if job.state != "done":
        raise AppError("ANALYSIS_NOT_READY")
    return job.result


@router.post("/analyses/{analysisId}/retry", status_code=202, response_model=RetryAccepted)
async def retry_analysis(analysisId: int, request: Request, jobs: JobStore = Depends(get_jobs)):
    """4-4 분석 재시도. FAILED인 분석만 같은 입력으로 다시 실행한다."""
    entry, job = _lookup(request, jobs, analysisId)
    if job.state != "failed":
        raise AppError("ANALYSIS_NOT_FAILED")
    _start(request, jobs, analysisId, entry.kind, entry.factory)
    return RetryAccepted(analysisId=analysisId)
