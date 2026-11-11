"""외부 공개(터널) 대비 요청 검사: API 키, 키 반복 실패 차단, IP별 요청 수 제한, 본문 크기 제한.

서버는 127.0.0.1에만 열고 터널(ngrok)이 같은 PC에서 요청을 넘겨주므로,
루프백에서 온 요청에 한해 X-Forwarded-For의 첫 IP를 실제 클라이언트 IP로 본다.
상태는 프로세스 메모리에 둔다(워커 1개 전제).
"""

import logging
import secrets
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.errors import AppError

logger = logging.getLogger(__name__)

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_DOC_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
_UPLOAD_PATHS = {"/api/v1/trainings"}  # 첨부파일(multipart)을 받는 경로


def client_ip(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if host in _LOOPBACK and forwarded:
        return forwarded.split(",")[0].strip()
    return host


class _Limiter:
    def __init__(self, settings: Settings):
        self.s = settings
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.fails: dict[str, deque[float]] = defaultdict(deque)
        self.blocked: dict[str, float] = {}
        self._last_prune = 0.0

    @staticmethod
    def _trim(q: deque[float], since: float) -> None:
        while q and q[0] < since:
            q.popleft()

    def _prune(self, now: float) -> None:
        if now - self._last_prune < 60:
            return
        self._last_prune = now
        for store, window in ((self.hits, 60), (self.fails, self.s.auth_fail_window_sec)):
            for ip in [ip for ip, q in store.items() if not q or q[-1] < now - window]:
                del store[ip]
        for ip in [ip for ip, until in self.blocked.items() if until < now]:
            del self.blocked[ip]

    def is_blocked(self, ip: str, now: float) -> bool:
        return self.blocked.get(ip, 0) > now

    def over_rate(self, ip: str, now: float) -> bool:
        self._prune(now)
        q = self.hits[ip]
        self._trim(q, now - 60)
        q.append(now)
        return len(q) > self.s.rate_limit_per_min

    def auth_failed(self, ip: str, now: float) -> None:
        q = self.fails[ip]
        self._trim(q, now - self.s.auth_fail_window_sec)
        q.append(now)
        if len(q) >= self.s.auth_fail_limit:
            self.blocked[ip] = now + self.s.auth_block_sec
            q.clear()
            logger.warning("API 키 반복 실패로 %s 를 %d초 차단", ip, self.s.auth_block_sec)


def _error(code: str, message: str | None = None) -> JSONResponse:
    e = AppError(code, message=message)
    return JSONResponse(status_code=e.status, content=e.body())


def install(app: FastAPI, settings: Settings) -> None:
    key = settings.api_key
    if not key:
        logger.warning("API_KEY가 설정되지 않아 누구나 호출할 수 있습니다. 외부에 공개할 때는 반드시 설정하세요.")
    limiter = _Limiter(settings)

    @app.middleware("http")
    async def _guard(request: Request, call_next):
        now = time.monotonic()
        ip = client_ip(request)
        path = request.url.path

        if limiter.is_blocked(ip, now):
            return _error("RATE_LIMITED", "인증 실패가 반복되어 잠시 차단되었어요. 10분 뒤 다시 시도해 주세요.")
        if limiter.over_rate(ip, now):
            return _error("RATE_LIMITED")

        length = request.headers.get("content-length")
        limit = settings.max_upload_bytes if path in _UPLOAD_PATHS else settings.max_body_bytes
        if length and length.isdigit() and int(length) > limit:
            return _error("FILE_TOO_LARGE" if path in _UPLOAD_PATHS else "INPUT_TOO_LONG")

        authed = not key or secrets.compare_digest(request.headers.get("x-api-key", "").encode(), key.encode())
        request.state.authed = authed
        open_path = path == "/health" or (settings.public_docs and path in _DOC_PATHS) or request.method == "OPTIONS"
        if not authed and not open_path:
            if request.headers.get("x-api-key"):
                limiter.auth_failed(ip, now)  # 틀린 키만 센다. 키 없는 단순 접속은 401만 돌려준다.
            return _error("UNAUTHORIZED")
        return await call_next(request)
