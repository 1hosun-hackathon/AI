import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routes import router
from app.config import Settings
from app.jobs.store import InMemoryJobStore
from app.llm.base import LLMProvider
from app.llm.ollama import OllamaProvider
from app.pipelines.context import Ctx
from app.prompts.loader import Prompts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")


async def _warmup(llm: LLMProvider) -> None:
    """첫 요청이 모델 로딩(최대 1분 이상)을 떠안지 않도록 미리 한 번 호출한다."""
    try:
        await llm.chat([{"role": "user", "content": "안녕"}])
        await llm.embed(["준비"])
        logger.info("워밍업 완료: %s, %s", llm.model_name, llm.embed_model_name)
    except Exception as e:  # noqa: BLE001 - 워밍업 실패는 서버 시작을 막지 않는다
        logger.warning("워밍업 실패: %r", e)


def create_app(settings: Settings | None = None, llm: LLMProvider | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        provider = llm or OllamaProvider(settings)
        jobs = InMemoryJobStore(ttl_sec=settings.job_ttl_sec, max_queue=settings.job_queue_max)
        app.state.ctx = Ctx(llm=provider, settings=settings, prompts=Prompts(settings.prompt_version))
        app.state.jobs = jobs
        await jobs.start()
        warmup = asyncio.create_task(_warmup(provider)) if settings.warmup else None
        yield
        if warmup:
            warmup.cancel()
        await jobs.stop()
        if hasattr(provider, "aclose"):
            await provider.aclose()

    app = FastAPI(title="글적글적 AI 서버", version="0.1.0", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
