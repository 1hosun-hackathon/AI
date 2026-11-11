"""테스트용 가짜 LLM. 응답은 responder(messages, schema)가 정한다."""

import json
from collections.abc import Callable
from typing import Any

import numpy as np

from app.llm.mock import DIM, bigram_vector

Responder = Callable[[list[dict], dict | None], Any]
__all__ = ["DIM", "FakeProvider", "bigram_vector"]


class FakeProvider:
    model_name = "fake-llm"
    embed_model_name = "fake-embed"

    def __init__(self, responder: Responder | None = None):
        self.responder = responder or (lambda m, s: "")
        self.calls: list[tuple[list[dict], dict | None]] = []

    async def chat(self, messages, *, schema=None, temperature=0.0) -> str:
        self.calls.append((list(messages), schema))
        out = self.responder(messages, schema)
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)

    async def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        return np.stack([bigram_vector(t) for t in texts])

    async def ping(self) -> bool:
        return True

    def calls_for(self, title: str) -> list:
        return [c for c in self.calls if c[1] and c[1].get("title") == title]
