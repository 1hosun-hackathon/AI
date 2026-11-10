import pytest

from app.llm.base import LLMOutputError
from app.llm.outputs import ItemEvalOutput, SummaryOutput
from app.llm.structured import clean_json_text, generate_structured, inline_schema
from tests.fakes import FakeProvider

VALID_SUMMARY = {
    "overall_report": "리포트",
    "strengths": ["강점"],
    "improvements": ["보완"],
    "questions": ["무엇이 중요한가?", "왜 그렇게 생각하는가?"],
}


def test_clean_json_text_strips_fence_and_think():
    raw = '<think>생각</think>\n```json\n{"a": 1}\n```'
    assert clean_json_text(raw) == '{"a": 1}'


def test_inline_schema_has_no_refs():
    schema = inline_schema(ItemEvalOutput)
    assert "$defs" not in schema and "$ref" not in str(schema)
    assert schema["properties"]["a_score"]["enum"] == [1, 2, 3, 4, 5]
    # 생성 순서 = 필드 순서: 요약 → 근거 → 비교 → 점수
    keys = list(schema["properties"])
    assert keys.index("evidence") < keys.index("comparison") < keys.index("a_score")


async def test_retries_once_with_error_message():
    outputs = iter(["{깨진 json", VALID_SUMMARY])
    llm = FakeProvider(lambda m, s: next(outputs))
    out = await generate_structured(llm, [{"role": "user", "content": "x"}], SummaryOutput)
    assert out.strengths == ["강점"]
    assert len(llm.calls) == 2
    retry_messages = llm.calls[1][0]
    assert retry_messages[-1]["role"] == "user" and "검증에 실패" in retry_messages[-1]["content"]


async def test_raises_after_retry_exhausted():
    llm = FakeProvider(lambda m, s: {"overall_report": "", "strengths": []})
    with pytest.raises(LLMOutputError):
        await generate_structured(llm, [{"role": "user", "content": "x"}], SummaryOutput)
    assert len(llm.calls) == 2
