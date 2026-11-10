import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import AppError
from app.llm.base import LLMError

logger = logging.getLogger(__name__)


def _respond(e: AppError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content=e.body())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError) -> JSONResponse:
        return _respond(e)

    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, e: LLMError) -> JSONResponse:
        logger.warning("LLM 오류: %r", e)
        return _respond(AppError(e.code, detail=str(e)))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        fields = sorted({str(err["loc"][-1]) for err in e.errors() if err.get("loc")})
        msg = f"입력값을 확인해 주세요: {', '.join(fields)}" if fields else None
        return _respond(AppError("INVALID_INPUT", message=msg))
