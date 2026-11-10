"""테스트용 가짜 LLM. 응답은 responder(messages, schema)가 정한다."""

import json
import zlib
from collections.abc import Callable
from typing import Any

import numpy as np

from app.text.sentences import compact

DIM = 512
Responder = Callable[[list[dict], dict | None], Any]


def bigram_vector(text: str) -> np.ndarray:
    """글자 bigram 해시 벡터. 같은 문장이면 유사도 1, 다른 문장이면 낮게 나온다."""
    t = compact(text)
    v = np.zeros(DIM, dtype=np.float32)
    for i in range(len(t) - 1):
        v[zlib.crc32(t[i : i + 2].encode("utf-8")) % DIM] += 1.0
    n = np.linalg.norm(v)
    return v / n if n else v


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
