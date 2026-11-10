from fastapi import Request

from app.config import Settings
from app.errors import AppError
from app.jobs.store import JobStore
from app.pipelines.context import Ctx


def get_ctx(request: Request) -> Ctx:
    return request.app.state.ctx


def get_jobs(request: Request) -> JobStore:
    return request.app.state.jobs


def check_lengths(settings: Settings, *texts: str) -> None:
    limit = settings.max_draft_chars
    if any(len(t) > limit for t in texts):
        raise AppError("INPUT_TOO_LONG", message=f"글이 너무 길어요. 한 편당 {limit}자 이하로 줄여 주세요.")
