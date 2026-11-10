"""스키마 강제 호출 → 정리 → Pydantic 검증 → 실패 시 오류를 알려주고 재시도."""

import copy
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.base import LLMOutputError, LLMProvider, Message

T = TypeVar("T", bound=BaseModel)

_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE_START = re.compile(r"^```[a-zA-Z]*\s*")
_FENCE_END = re.compile(r"\s*```$")


def clean_json_text(text: str) -> str:
    text = _THINK.sub("", text).strip()
    text = _FENCE_START.sub("", text)
    return _FENCE_END.sub("", text).strip()


def inline_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """$defs/$ref를 펼친 JSON 스키마. 문법 강제 디코더가 참조 없이 해석하게 한다."""
    schema = model_cls.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolve(copy.deepcopy(defs[ref.split("/")[-1]]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def _short_errors(e: ValidationError, limit: int = 5) -> str:
    lines = []
    for err in e.errors()[:limit]:
        loc = ".".join(str(p) for p in err["loc"]) or "(전체)"
        lines.append(f"- {loc}: {err['msg']}")
    return "\n".join(lines)


async def generate_structured(
    llm: LLMProvider,
    messages: list[Message],
    model_cls: type[T],
    *,
    temperature: float = 0.0,
    retries: int = 1,
) -> T:
    schema = inline_schema(model_cls)
    msgs = list(messages)
    last_error: ValidationError | None = None
    for _ in range(retries + 1):
        raw = await llm.chat(msgs, schema=schema, temperature=temperature)
        try:
            return model_cls.model_validate_json(clean_json_text(raw))
        except ValidationError as e:
            last_error = e
            msgs = msgs + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": f"출력이 형식 검증에 실패했다.\n{_short_errors(e)}\n오류를 고친 JSON만 다시 출력하라.",
                },
            ]
    raise LLMOutputError(f"{model_cls.__name__} 검증 실패: {last_error}")
