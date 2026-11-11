"""비동기 job. MVP는 인메모리 + 작업자 1개. Redis 등으로 바꿀 때는 JobStore 구현만 교체한다.

주의: uvicorn 워커가 여러 개면 프로세스마다 저장소가 따로 생기므로 워커는 1개로 실행한다.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from app.errors import AppError
from app.llm.base import LLMError

logger = logging.getLogger(__name__)

JobFactory = Callable[[], Awaitable[BaseModel]]


@dataclass
class Job:
    id: str
    kind: str
    state: str = "queued"  # queued | running | done | failed
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class QueueFullError(Exception):
    pass


class JobStore(Protocol):
    def submit(self, kind: str, factory: JobFactory) -> Job: ...
    def get(self, job_id: str) -> Job | None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class InMemoryJobStore:
    def __init__(self, ttl_sec: int, max_queue: int):
        self._ttl = ttl_sec
        self._jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[tuple[Job, JobFactory]] = asyncio.Queue(maxsize=max_queue)
        self._worker: asyncio.Task | None = None

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    def submit(self, kind: str, factory: JobFactory) -> Job:
        self._purge()
        job = Job(id=str(uuid.uuid4()), kind=kind)
        try:
            self._queue.put_nowait((job, factory))
        except asyncio.QueueFull as e:
            raise QueueFullError from e
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        self._purge()
        return self._jobs.get(job_id)

    async def _run(self) -> None:
        while True:
            job, factory = await self._queue.get()
            job.state = "running"
            started = time.time()
            try:
                result = await factory()
                job.result = result.model_dump(mode="json")
                job.state = "done"
            except AppError as e:
                job.error, job.state = e.body()["error"], "failed"
            except LLMError as e:
                job.error, job.state = AppError(e.code, detail=str(e)).body()["error"], "failed"
            except Exception:  # noqa: BLE001 - 작업자가 죽지 않게 모든 예외를 job 실패로 기록
                logger.exception("job %s 실패", job.id)
                job.error, job.state = AppError("INTERNAL").body()["error"], "failed"
            finally:
                job.finished_at = time.time()
                self._queue.task_done()
                logger.info("job %s %s %s %.1fs", job.id, job.kind, job.state, job.finished_at - started)

    def _purge(self) -> None:
        now = time.time()
        expired = [jid for jid, j in self._jobs.items() if j.finished_at and now - j.finished_at > self._ttl]
        for jid in expired:
            del self._jobs[jid]
