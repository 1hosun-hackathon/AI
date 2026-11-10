from typing import Any, Literal

from pydantic import BaseModel

JobState = Literal["queued", "running", "done", "failed"]


class JobCreated(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    job_id: str
    state: JobState
    result: dict[str, Any] | None = None  # AnalysisResult 또는 ReanalysisResult
    error: dict[str, Any] | None = None  # {"code", "message", "retryable"}
