"""노션 API 명세 경로(/api/v1/...)의 AI 부분. 기존 파이프라인을 쓰고 요청·응답만 변환한다.

백엔드가 같은 경로·ID(trainingId, analysisId)로 이 서버를 호출하면 된다.
분석 결과는 서버 메모리에 JOB_TTL_SEC 동안만 남으므로, SUCCESS가 되면 백엔드가 4-2 결과를 받아 저장한다.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePath

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

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
    AnalysisStatusResponse,
    AnalysisSummary,
    Attachment,
    ComparisonAnalysis,
    CompleteRequest,
    CompleteResponse,
    CriterionScore,
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

# 2-1 첨부파일: PDF·PPT·문서·이미지, 파일당 10MB, 5개까지(명세 가정값)
_ALLOWED_EXT = {
    ".pdf", ".ppt", ".pptx", ".doc", ".docx", ".hwp", ".hwpx", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
}  # fmt: skip
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_FILES = 5


@dataclass
class _Analysis:
    job_id: str
    kind: str
    factory: JobFactory
    training_id: int
    seq_no: int
    created_at: str


def _registry(request: Request) -> dict[int, _Analysis]:
    if not hasattr(request.app.state, "analyses"):
        request.app.state.analyses = {}
    return request.app.state.analyses


def _now() -> str:
    return datetime.now(_KST).isoformat(timespec="seconds")


def _requirements(task: Task) -> Requirements:
    # "800~1,000자, 근거 2개 이상"에서 분량을 해석하고, 나머지 조건도 그대로 모델에 전달된다.
    return Requirements(format=task.writingType, length=task.requirements)


def _require_content(*texts: str) -> None:
    if any(not t.strip() for t in texts):
        raise AppError("EMPTY_CONTENT")


def _criterion(key: str) -> str:
    return key.upper()


def to_result(res: core.AnalysisResult, meta: dict) -> ComparisonAnalysis:
    return ComparisonAnalysis(
        **meta,
        overallSummary=res.overall_report,
        strengths="\n".join(res.strengths),
        improvements="\n".join(res.improvements),
        items=[
            AnalysisItem(
                criterion=_criterion(it.key),
                label=LABELS[_criterion(it.key)][0],
                description=LABELS[_criterion(it.key)][1],
                userSummary=it.user_summary,
                aiSummary=it.ai_summary,
                comparison=it.comparison,
                reflectPoint=it.action_item,
            )
            for it in res.items
        ],
        questions=[Question(seqNo=i, content=q) for i, q in enumerate(res.questions, 1)],
        scores=[
            CriterionScore(
                criterion=_criterion(it.key),
                userScore=it.user_score,
                aiScore=it.ai_score,
                better=it.better,
                evidence=[EvidenceQuote(**e.model_dump()) for e in it.evidence],
            )
            for it in res.items
        ],
        reflectionReviews=[
            ReflectionReview(criterion=_criterion(r.key), reflectPoint=r.action_item, reflected=r.reflected, reason=r.reason)
            for r in getattr(res, "action_item_review", [])
        ],
        scoreDelta={_criterion(k): v for k, v in getattr(res, "score_delta", {}).items()},
        partial=res.status != "done",
        warnings=res.warnings,
        promptVersion=res.prompt_version,
        model=res.model,
    )


def from_result(prev: ComparisonAnalysis) -> core.AnalysisResult:
    """previousResult를 재분석 파이프라인 형식으로 되돌린다."""
    scores = {s.criterion: s for s in prev.scores}
    missing = [it.criterion for it in prev.items if it.criterion not in scores]
    if missing:
        raise AppError("VALIDATION_ERROR", message=f"previousResult.scores에 빠진 항목이 있어요: {', '.join(missing)}")
    return core.AnalysisResult(
        status="partial" if prev.partial else "done",
        items=[
            core.ItemResult(
                key=it.criterion.lower(),
                user_score=scores[it.criterion].userScore,
                ai_score=scores[it.criterion].aiScore,
                user_summary=it.userSummary,
                ai_summary=it.aiSummary,
                comparison=it.comparison,
                evidence=[core.Evidence(**e.model_dump()) for e in scores[it.criterion].evidence],
                better=scores[it.criterion].better,
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


class _AiWritingCache:
    """AI 작성 글이 없으면(2-1 생성 실패) 분석 job 안에서 먼저 만든다. 재시도 때는 이미 만든 글을 다시 쓴다."""

    def __init__(self, ctx: Ctx, req: DraftSubmitRequest):
        self.ctx, self.req = ctx, req
        given = req.aiWriting.content if req.aiWriting else ""
        self.text: str | None = given if given.strip() else None

    async def get(self) -> str:
        if self.text is None:
            res = await reference_draft.run(
                self.ctx, ReferenceDraftRequest(topic=self.req.topic, requirements=_requirements(self.req))
            )
            self.text = res.draft
        return self.text


def _start(request: Request, jobs: JobStore, analysis_id: int, entry: _Analysis) -> None:
    entry.job_id = _submit(jobs, entry.kind, entry.factory).job_id
    _registry(request)[analysis_id] = entry


def _lookup(request: Request, jobs: JobStore, analysis_id: int):
    entry = _registry(request).get(analysis_id)
    job = jobs.get(entry.job_id) if entry else None
    if job is None:
        _registry(request).pop(analysis_id, None)
        raise AppError("ANALYSIS_NOT_FOUND")
    return entry, job


async def _parse_training_create(request: Request) -> tuple[TrainingCreateRequest, list[Attachment]]:
    """2-1 요청: multipart/form-data(request 파트 JSON + files 파트 0개 이상) 또는 JSON 본문."""
    try:
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            form = await request.form()
            part = form.get("request")
            raw = await part.read() if hasattr(part, "read") else (part or "")
            req = TrainingCreateRequest.model_validate_json(raw)
            files = [f for f in form.getlist("files") if hasattr(f, "filename") and f.filename]
        else:
            req = TrainingCreateRequest.model_validate(await request.json())
            files = []
    except ValidationError as e:
        raise RequestValidationError(e.errors()) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AppError("VALIDATION_ERROR", message="요청 본문을 JSON으로 읽을 수 없어요.") from None

    if len(files) > _MAX_FILES:
        raise AppError("FILE_TOO_LARGE")
    attachments = []
    for f in files:
        if PurePath(f.filename).suffix.lower() not in _ALLOWED_EXT:
            raise AppError("FILE_TYPE_NOT_ALLOWED")
        size = len(await f.read())  # 첨부 내용은 쓰지 않고 크기만 확인한다
        if size > _MAX_FILE_BYTES:
            raise AppError("FILE_TOO_LARGE")
        attachments.append(Attachment(fileName=f.filename, fileSize=size))
    return req, attachments


_TRAINING_CREATE_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["request"],
                    "properties": {
                        "request": {"$ref": "#/components/schemas/TrainingCreateRequest"},
                        "files": {"type": "array", "items": {"type": "string", "format": "binary"}},
                    },
                },
                "encoding": {"request": {"contentType": "application/json"}},
            },
            "application/json": {"schema": {"$ref": "#/components/schemas/TrainingCreateRequest"}},
        },
    }
}


@router.post("/trainings", status_code=201, response_model=TrainingCreateResponse, openapi_extra=_TRAINING_CREATE_BODY)
async def create_training(request: Request, ctx: Ctx = Depends(get_ctx)):
    """2-1 훈련 생성: 과제 조건만으로 AI 작성 글을 만든다(동기, 수십 초). 첨부파일은 받기만 하고 글에 반영하지 않는다."""
    req, attachments = await _parse_training_create(request)
    res = await reference_draft.run(ctx, ReferenceDraftRequest(topic=req.topic, requirements=_requirements(req)))
    analyze.prescore_ai(ctx, req.topic, res.draft)  # 학습자가 초안을 쓰는 동안 AI 글을 미리 채점
    return TrainingCreateResponse(
        trainingId=req.trainingId,
        aiWriting=AiWriting(content=res.draft),
        attachments=attachments,
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
    _require_content(req.content)
    ai = _AiWritingCache(ctx, req)
    check_lengths(ctx.settings, req.content, ai.text or "")
    created_at = _now()

    async def job():
        ai_text = await ai.get()
        core_req = core.AnalyzeRequest(
            topic=req.topic, requirements=_requirements(req), user_draft=req.content, ai_draft=ai_text
        )
        meta = dict(
            analysisId=req.analysisId,
            trainingId=trainingId,
            seqNo=0,
            createdAt=created_at,
            myWriting=Writing(versionId=req.versionId, content=req.content),
            aiWriting=AiWriting(content=ai_text),
        )
        return to_result(await analyze.run(ctx, core_req), meta)

    _start(request, jobs, req.analysisId, _Analysis("", "analyze", job, trainingId, 0, created_at))
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
    _require_content(req.content, req.baseline.content)
    if req.content.strip() == req.previousResult.myWriting.content.strip():
        raise AppError("NO_CHANGES")
    # 다시 검사는 AI 작성 글을 재사용한다. 요청에 없으면 직전 결과의 aiWriting을 쓴다.
    if not (req.aiWriting and req.aiWriting.content.strip()):
        req.aiWriting = req.previousResult.aiWriting
    ai = _AiWritingCache(ctx, req)
    check_lengths(ctx.settings, req.baseline.content, req.content, ai.text or "")
    previous = from_result(req.previousResult)
    created_at = _now()

    async def job():
        ai_text = await ai.get()
        core_req = core.ReanalyzeRequest(
            topic=req.topic,
            requirements=_requirements(req),
            original_draft=req.baseline.content,
            current_draft=req.content,
            ai_draft=ai_text,
            previous_result=previous,
            round=req.seqNo + 1,
        )
        meta = dict(
            analysisId=req.analysisId,
            trainingId=trainingId,
            seqNo=req.seqNo,
            createdAt=created_at,
            myWriting=Writing(versionId=req.versionId, content=req.content),
            aiWriting=AiWriting(content=ai_text),
            baseline=req.baseline,
        )
        return to_result(await reanalyze.run(ctx, core_req), meta)

    _start(request, jobs, req.analysisId, _Analysis("", "reanalyze", job, trainingId, req.seqNo, created_at))
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
        finalVersionId=req.finalVersionId,
        completedAt=_now(),
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


@router.get("/trainings/{trainingId}/analyses", response_model=list[AnalysisSummary])
async def list_analyses(trainingId: int, request: Request, jobs: JobStore = Depends(get_jobs)):
    """4-3 회차별 분석 목록(seqNo 오름차순). AI 서버 메모리에 남아 있는 분석만 나온다."""
    rows = []
    for analysis_id, entry in list(_registry(request).items()):
        if entry.training_id != trainingId:
            continue
        job = jobs.get(entry.job_id)
        if job is None:
            _registry(request).pop(analysis_id, None)
            continue
        rows.append(
            AnalysisSummary(analysisId=analysis_id, seqNo=entry.seq_no, status=_STATUS[job.state], createdAt=entry.created_at)
        )
    return sorted(rows, key=lambda r: (r.seqNo, r.analysisId))


@router.post("/analyses/{analysisId}/retry", status_code=202, response_model=RetryAccepted)
async def retry_analysis(analysisId: int, request: Request, jobs: JobStore = Depends(get_jobs)):
    """4-4 분석 재시도. FAILED인 분석만 같은 입력으로 다시 실행한다. AI 작성 글이 없던 분석은 그것부터 다시 만든다."""
    entry, job = _lookup(request, jobs, analysisId)
    if job.state != "failed":
        raise AppError("ANALYSIS_NOT_FAILED")
    _start(request, jobs, analysisId, entry)
    return RetryAccepted(analysisId=analysisId)
