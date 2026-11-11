from typing import Any, Protocol, TypedDict

import numpy as np


class Message(TypedDict):
    role: str  # system | user | assistant
    content: str


class LLMError(Exception):
    code = "LLM_UNAVAILABLE"


class LLMTimeout(LLMError):
    code = "LLM_TIMEOUT"


class LLMUnavailable(LLMError):
    code = "LLM_UNAVAILABLE"


class LLMOutputError(LLMError):
    code = "LLM_OUTPUT_INVALID"


class LLMProvider(Protocol):
    """파이프라인이 의존하는 유일한 LLM 인터페이스. 구현: OllamaProvider, 테스트용 FakeProvider."""

    model_name: str
    embed_model_name: str

    async def chat(
        self, messages: list[Message], *, schema: dict[str, Any] | None = None, temperature: float = 0.0
    ) -> str:
        """schema가 있으면 그 JSON 스키마로 출력을 강제한다. 원문 문자열을 돌려준다."""
        ...

    async def embed(self, texts: list[str]) -> np.ndarray:
        """L2 정규화된 (len(texts), dim) 배열."""
        ...

    async def ping(self) -> bool: ...
