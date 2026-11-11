import asyncio
from typing import Any

import httpx
import numpy as np

from app.config import Settings
from app.llm.base import LLMTimeout, LLMUnavailable, Message


class OllamaProvider:
    """Ollama 네이티브 API(/api/chat, /api/embed)를 httpx로 직접 호출한다."""

    def __init__(self, settings: Settings):
        self._s = settings
        self.model_name = settings.llm_model
        self.embed_model_name = settings.embed_model
        self._client = httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=settings.llm_timeout_sec)
        # GPU 한 장의 Ollama는 사실상 순차 처리하므로 동시 호출 수를 제한한다.
        self._sem = asyncio.Semaphore(settings.llm_concurrency)

    async def chat(
        self, messages: list[Message], *, schema: dict[str, Any] | None = None, temperature: float = 0.0
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "keep_alive": self._s.llm_keep_alive,
            "options": {"temperature": temperature, "seed": self._s.llm_seed, "num_ctx": self._s.llm_num_ctx},
        }
        if self._s.think_value is not None:
            body["think"] = self._s.think_value
        if schema is not None:
            body["format"] = schema
        data = await self._post("/api/chat", body)
        return data.get("message", {}).get("content", "")

    async def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        data = await self._post(
            "/api/embed", {"model": self.embed_model_name, "input": texts, "keep_alive": self._s.llm_keep_alive}
        )
        arr = np.asarray(data["embeddings"], dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.clip(norms, 1e-12, None)

    async def ping(self) -> bool:
        try:
            r = await self._client.get("/api/tags", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self._sem:
            try:
                r = await self._client.post(path, json=body)
            except httpx.TimeoutException as e:
                raise LLMTimeout(f"{path} timeout") from e
            except httpx.TransportError as e:
                raise LLMUnavailable(f"{path} 연결 실패: {e}") from e
        if r.status_code >= 400:
            raise LLMUnavailable(f"{path} HTTP {r.status_code}: {r.text[:200]}")
        return r.json()
