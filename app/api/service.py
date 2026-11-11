"""백엔드 API 명세 형식 엔드포인트(/ai/v2). 기존 파이프라인을 그대로 쓰고 요청·응답만 변환한다."""

from fastapi import APIRouter, Depends

from app.api.deps import check_lengths, get_ctx, get_jobs
from app.api.routes import _submit
from app.errors import AppError
from app.jobs.store import JobStore
from app.pipelines import analyze, dependency, reanalyze, reference_draft
from app.pipelines.context import Ctx
from app.schemas import analysis as core
from app.schemas.common import CRITERIA_INFO, Requirements
from app.schemas.dependency import DependencyRequest
from app.schemas.draft import ReferenceDraftRequest
from app.schemas.service import (
    AiWritingRequest,
    AiWritingResponse,
    AnalysisAccepted,
    AnalysisItem,
    AnalysisJob,
    AnalysisReport,
    AnalysisRequest,
    EvidenceQuote,
    Question,
    RatioRequest,
    RatioResponse,
    RatioSentence,
    ReflectionReview,
    TaskInfo,
)

router = APIRouter(prefix="/ai/v2", tags=["백엔드 명세 형식"])

_STATUS = {"queued": "PENDING", "running": "GENERATING", "done": "SUCCESS", "failed": "FAILED"}


def _requirements(task: TaskInfo) -> Requirements:
    # 과제 조건 문자열 안의 "800~1,000자"를 분량으로 해석하고, 나머지 조건도 그대로 모델에 전달된다.
    return Requirements(format=task.writingType, length=task.requirements)


def _criterion(key: str) -> str:
    return key.upper()


def to_report(res: core.AnalysisResult, seq_no: int) -> AnalysisReport:
    reviews = getattr(res, "action_item_review", [])
    delta = getattr(res, "score_delta", {})
    return AnalysisReport(
        seqNo=seq_no,
        overallSummary=res.overall_report,
        strengths="\n".join(res.strengths),
        improvements="\n".join(res.improvements),
        items=[
            AnalysisItem(
                criterion=_criterion(it.key),
                label=CRITERIA_INFO[it.key][0],
                description=CRITERIA_INFO[it.key][1],
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
            ReflectionReview(criterion=_criterion(r.key), reflectPoint=r.action_item, reflected=r.reflected, reason=r.reason)
            for r in reviews
        ],
        scoreDelta={_criterion(k): v for k, v in delta.items()},
        partial=res.status != "done",
        warnings=res.warnings,
        promptVersion=res.prompt_version,
        model=res.model,
    )


def from_report(rep: AnalysisReport) -> core.AnalysisResult:
    """previousResult를 재분석 파이프라인이 쓰는 형식으로 되돌린다."""
    return core.AnalysisResult(
        status="partial" if rep.partial else "done",
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
            for it in rep.items
        ],
        overall_report=rep.overallSummary,
        strengths=[s for s in rep.strengths.split("\n") if s],
        improvements=[s for s in rep.improvements.split("\n") if s],
        questions=[q.content for q in rep.questions],
        warnings=rep.warnings,
        prompt_version=rep.promptVersion,
        model=rep.model,
    )


@router.post("/ai-writing", response_model=AiWritingResponse)
async def create_ai_writing(req: AiWritingRequest, ctx: Ctx = Depends(get_ctx)):
    """2-1 훈련 생성 직후(또는 4-4 재시도 시) AI 작성 글을 만든다. 동기 호출."""
    res = await reference_draft.run(ctx, ReferenceDraftRequest(topic=req.topic, requirements=_requirements(req)))
    return AiWritingResponse(
        content=res.draft, charCount=res.char_count, warnings=res.warnings, promptVersion=res.prompt_version, model=res.model
    )


@router.post("/analyses", status_code=202, response_model=AnalysisAccepted)
async def submit_analysis(req: AnalysisRequest, ctx: Ctx = Depends(get_ctx), jobs: JobStore = Depends(get_jobs)):
    """3-2 초안 제출(seqNo 0) 또는 3-4 다시 검사하기(seqNo≥1)의 비교 분석을 시작한다."""
    common = dict(topic=req.topic, requirements=_requirements(req), ai_draft=req.aiWriting.content)
    if req.seqNo == 0:
        check_lengths(ctx.settings, req.myWriting.content, req.aiWriting.content)
        core_req = core.AnalyzeRequest(**common, user_draft=req.myWriting.content)

        async def job():
            return to_report(await analyze.run(ctx, core_req), 0)

        created = _submit(jobs, "analyze", job)
    else:
        if req.baseline is None or req.previousResult is None:
            raise AppError("INVALID_INPUT", message="다시 검사하려면 최초 초안(baseline)과 직전 분석 결과(previousResult)가 필요해요.")
        check_lengths(ctx.settings, req.baseline.content, req.myWriting.content, req.aiWriting.content)
        core_req = core.ReanalyzeRequest(
            **common,
            original_draft=req.baseline.content,
            current_draft=req.myWriting.content,
            previous_result=from_report(req.previousResult),
            round=req.seqNo + 1,
        )

        async def job():
            return to_report(await reanalyze.run(ctx, core_req), req.seqNo)

        created = _submit(jobs, "reanalyze", job)
    return AnalysisAccepted(jobId=created.job_id)


@router.get("/analyses/{job_id}", response_model=AnalysisJob)
async def get_analysis(job_id: str, jobs: JobStore = Depends(get_jobs)):
    """4-1 분석 상태 폴링. SUCCESS면 result를 4-2 결과로 저장한다."""
    job = jobs.get(job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND")
    return AnalysisJob(jobId=job.id, status=_STATUS[job.state], result=job.result, error=job.error)


@router.post("/self-thought-ratio", response_model=RatioResponse)
async def compute_ratio(req: RatioRequest, ctx: Ctx = Depends(get_ctx)):
    """3-5 훈련 완료 시 자기 사고 비율·AI 의존도(%)를 계산한다. LLM 미사용, 동기 호출."""
    check_lengths(ctx.settings, req.draft.content, req.finalWriting.content, req.aiWriting.content)
    res = await dependency.run(
        ctx,
        DependencyRequest(user_draft=req.draft.content, final_text=req.finalWriting.content, ai_draft=req.aiWriting.content),
    )
    ai = round(res.ai_dependency_ratio * 100, 1)
    return RatioResponse(
        selfThoughtRatio=round(100 - ai, 1),
        aiDependencyRatio=ai,
        sentences=[RatioSentence(text=s.text, label=s.label, simUser=s.sim_user, simAi=s.sim_ai) for s in res.sentences],
        method=res.method.description,
        promptVersion=res.prompt_version,
        model=res.model,
    )
