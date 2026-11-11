import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from pydantic.json_schema import models_json_schema

from app.api.errors import register_error_handlers
from app.api.routes import router
from app.api.service import router as service_router
from app.config import Settings
from app.errors import AppError
from app.jobs.store import InMemoryJobStore
from app.llm.base import LLMProvider
from app.llm.mock import MockProvider
from app.llm.ollama import OllamaProvider
from app.pipelines.context import Ctx
from app.prompts.loader import Prompts
from app.schemas.analysis import AnalysisResult, ReanalysisResult
from app.schemas.service import TrainingCreateRequest

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


def _make_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        logger.warning("가짜 응답 모드(LLM_PROVIDER=mock): 실제 모델을 호출하지 않습니다.")
        return MockProvider(delay_sec=settings.mock_delay_sec)
    return OllamaProvider(settings)


def create_app(settings: Settings | None = None, llm: LLMProvider | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        provider = llm or _make_provider(settings)
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
    _require_api_key(app, settings.api_key)
    app.include_router(router)
    app.include_router(service_router)
    app.openapi = lambda: _openapi(app)
    return app


_OPEN_PATHS = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def _require_api_key(app: FastAPI, api_key: str | None) -> None:
    """API_KEY가 설정돼 있으면 X-API-Key 헤더를 검사한다. 상태 확인과 문서는 키 없이 열어 둔다."""
    if not api_key:
        logger.warning("API_KEY가 설정되지 않아 누구나 호출할 수 있습니다. 외부에 공개할 때는 반드시 설정하세요.")
        return

    @app.middleware("http")
    async def _check_key(request: Request, call_next):
        if request.url.path in _OPEN_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        given = request.headers.get("x-api-key", "")
        if not secrets.compare_digest(given.encode(), api_key.encode()):
            e = AppError("UNAUTHORIZED")
            return JSONResponse(status_code=e.status, content=e.body())
        return await call_next(request)


def _openapi(app: FastAPI) -> dict:
    """job 결과 형식(AnalysisResult, ReanalysisResult)과 2-1 request 파트 형식을 명세 components에 넣는다."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    _, defs = models_json_schema(
        [
            (AnalysisResult, "serialization"),
            (ReanalysisResult, "serialization"),
            (TrainingCreateRequest, "validation"),  # 2-1 multipart request 파트
        ],
        ref_template="#/components/schemas/{model}",
    )
    # Swagger(/docs)의 Authorize 버튼으로 키를 넣을 수 있게 한다.
    schema.setdefault("components", {})["securitySchemes"] = {
        "ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }
    schema["security"] = [{"ApiKey": []}]
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, d in defs.get("$defs", {}).items():
        components.setdefault(name, d)
    app.openapi_schema = schema
    return schema


app = create_app()
