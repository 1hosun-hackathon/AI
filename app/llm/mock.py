"""가짜 응답 모드 (LLM_PROVIDER=mock).

백엔드·프론트 팀이 Ollama 없이 API를 붙여 볼 수 있게, 실제 파이프라인(문장 분리, 가드레일, job, 응답 조립)은
그대로 돌리고 LLM 호출만 고정된 형식의 응답으로 바꾼다. 점수는 글 내용의 해시로 정해서 같은 입력이면 같은 결과가 나온다.
"""

import asyncio
import json
import re
import zlib
from typing import Any

import numpy as np

from app.llm.base import Message
from app.schemas.common import CRITERIA
from app.text.sentences import compact

DIM = 512

_DRAFT_SENTENCES = [
    "이 글은 가짜 응답 모드에서 만든 참고 초안이다.",
    "실제 모델을 연결하면 과제 요구사항에 맞는 글이 이 자리에 들어간다.",
    "서론에서는 다루는 문제와 글의 목적을 밝힌다.",
    "본론에서는 근거와 자료를 제시하고 그 의미를 해석한다.",
    "결론에서는 본론의 내용을 정리하고 남은 한계를 짚는다.",
]


def bigram_vector(text: str) -> np.ndarray:
    """글자 bigram 해시 벡터. 같은 문장이면 유사도 1, 다른 문장이면 낮게 나온다."""
    t = compact(text)
    v = np.zeros(DIM, dtype=np.float32)
    for i in range(len(t) - 1):
        v[zlib.crc32(t[i : i + 2].encode("utf-8")) % DIM] += 1.0
    n = np.linalg.norm(v)
    return v / n if n else v


def _last_user(messages: list[Message]) -> str:
    return next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")


def _score(text: str) -> int:
    return 2 + zlib.crc32(text.encode("utf-8")) % 4  # 2~5


def _draft(prompt: str) -> str:
    m = re.search(r"(\d+)\s*~\s*(\d+)\s*자", prompt)
    target = (int(m.group(1)) + int(m.group(2))) // 2 if m else 800
    out: list[str] = []
    i = 0
    while sum(len(s) + 1 for s in out) < target:
        out.append(_DRAFT_SENTENCES[i % len(_DRAFT_SENTENCES)])
        i += 1
    # 다섯 문장씩 한 문단
    paras = [" ".join(out[j : j + 5]) for j in range(0, len(out), 5)]
    return "\n\n".join(paras)


def _respond(title: str, prompt: str) -> dict[str, Any]:
    score_item = {
        "summary": "가짜 응답: 이 항목에서 글의 짜임을 요약한 문장이 들어갑니다.",
        "evidence": [{"sentence_id": 1, "reason": "가짜 응답: 판단 근거가 된 문장입니다."}],
        "score": _score(prompt),
    }
    if title == "TextScoreOutput":
        return score_item
    if title == "TextScoreWithActionOutput":
        return score_item | {"action": "가짜 응답: 이 항목에서 보완할 방향이 한 문장으로 들어갑니다."}
    if title == "CompareOutput":
        return {
            "comparisons": [
                {"key": k, "comparison": "가짜 응답: 글 A와 글 B의 차이를 설명하는 문장이 들어갑니다."} for k in CRITERIA
            ]
        }
    if title == "SummaryOutput":
        return {
            "overall_report": "가짜 응답: 두 글의 구성과 근거 제시 방식의 차이를 정리한 종합 리포트가 들어갑니다.\n\n"
            "가짜 응답: 학습자 글의 현재 수준을 설명하는 두 번째 문단입니다.",
            "strengths": ["가짜 응답: 학습자 글의 강점입니다."],
            "improvements": ["가짜 응답: 학습자 글에서 보완할 점입니다."],
            "questions": [
                "가짜 응답: 서론에서 글의 목적이 드러나나요?",
                "가짜 응답: 결론은 본론의 어느 근거에서 나왔나요?",
                "가짜 응답: 자료와 자기 해석은 어떻게 구분했나요?",
            ],
        }
    if title == "FeedbackCheckOutput":
        return {"verdicts": []}  # 판정이 없으면 모두 ok로 처리된다
    if title == "ActionReviewOutput":
        return {
            "reviews": [
                {"key": k, "reflected": "partial", "reason": "가짜 응답: 반영 여부 판정 사유입니다."} for k in CRITERIA
            ]
        }
    raise ValueError(f"가짜 응답 모드가 모르는 출력 형식: {title}")


class MockProvider:
    model_name = "mock-llm"
    embed_model_name = "mock-embed"

    def __init__(self, delay_sec: float = 0.0):
        self.delay_sec = delay_sec

    async def chat(
        self, messages: list[Message], *, schema: dict[str, Any] | None = None, temperature: float = 0.0
    ) -> str:
        if self.delay_sec:
            await asyncio.sleep(self.delay_sec)
        prompt = _last_user(messages)
        if schema is None:
            return _draft(prompt)
        return json.dumps(_respond(schema.get("title", ""), prompt), ensure_ascii=False)

    async def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        return np.stack([bigram_vector(t) for t in texts])

    async def ping(self) -> bool:
        return True
