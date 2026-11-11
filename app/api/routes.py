from fastapi import APIRouter, Depends

from app.api.deps import check_lengths, get_ctx, get_jobs
from app.errors import AppError
from app.jobs.store import JobFactory, JobStore, QueueFullError
from app.pipelines import analyze, dependency, reanalyze, reference_draft
from app.pipelines.context import Ctx
from app.schemas.analysis import AnalyzeRequest, ReanalyzeRequest
from app.schemas.dependency import DependencyRequest, DependencyResponse
from app.schemas.draft import ReferenceDraftRequest, ReferenceDraftResponse
from app.schemas.jobs import JobCreated, JobStatus

router = APIRouter()


@router.get("/health")
async def health(ctx: Ctx = Depends(get_ctx)) -> dict:
    llm_up = await ctx.llm.ping()
    return {
        "status": "ok" if llm_up else "degraded",
        "llm": "up" if llm_up else "down",
        "model": ctx.llm.model_name,
        "embedding_model": ctx.llm.embed_model_name,
        "prompt_version": ctx.prompts.version,
    }


@router.post("/ai/reference-draft", response_model=ReferenceDraftResponse)
async def create_reference_draft(req: ReferenceDraftRequest, ctx: Ctx = Depends(get_ctx)):
    return await reference_draft.run(ctx, req)


def _submit(jobs: JobStore, kind: str, factory: JobFactory) -> JobCreated:
    try:
        return JobCreated(job_id=jobs.submit(kind, factory).id)
    except QueueFullError:
        raise AppError("QUEUE_FULL") from None


@router.post("/ai/analyze", status_code=202, response_model=JobCreated)
async def submit_analyze(req: AnalyzeRequest, ctx: Ctx = Depends(get_ctx), jobs: JobStore = Depends(get_jobs)):
    check_lengths(ctx.settings, req.user_draft, req.ai_draft)
    return _submit(jobs, "analyze", lambda: analyze.run(ctx, req))


@router.post("/ai/reanalyze", status_code=202, response_model=JobCreated)
async def submit_reanalyze(req: ReanalyzeRequest, ctx: Ctx = Depends(get_ctx), jobs: JobStore = Depends(get_jobs)):
    check_lengths(ctx.settings, req.original_draft, req.current_draft, req.ai_draft)
    return _submit(jobs, "reanalyze", lambda: reanalyze.run(ctx, req))


@router.get("/ai/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str, jobs: JobStore = Depends(get_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND")
    return JobStatus(job_id=job.id, state=job.state, result=job.result, error=job.error)


@router.post("/ai/dependency", response_model=DependencyResponse)
async def compute_dependency(req: DependencyRequest, ctx: Ctx = Depends(get_ctx)):
    check_lengths(ctx.settings, req.user_draft, req.final_text, req.ai_draft)
    return await dependency.run(ctx, req)
