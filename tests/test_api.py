import time

import pytest
from fastapi.testclient import TestClient

from app.llm.base import LLMUnavailable
from app.main import create_app
from app.schemas.common import CRITERIA
from tests.fakes import FakeProvider

TOPIC = "청소년의 스마트폰 사용 제한"
USER = "청소년의 스마트폰 사용은 제한해야 한다. 내 동생은 밤새 게임을 하다가 성적이 떨어졌다. 그래서 학교에서 걷어야 한다."
AI = "스마트폰 사용은 스스로 조절하도록 가르쳐야 한다. 통계청 조사에 따르면 과의존 위험군이 많다. 일괄 수거는 자기 조절 능력을 기를 기회를 빼앗는다."
CLEAN_ACTION = "주장을 뒷받침할 근거의 종류를 넓혀 보세요."


def _section(content: str, label: str) -> str:
    start = content.index(f"[글 {label}]")
    end = content.find("[글 ", start + 3)
    return content[start : end if end != -1 else None]


def scripted(action: str = CLEAN_ACTION, item_error: Exception | None = None):
    def respond(messages, schema):
        title = (schema or {}).get("title")
        content = messages[-1]["content"] if messages[-1]["role"] == "user" else ""
        prompt = messages[1]["content"]
        if title == "ItemEvalOutput":
            if item_error:
                raise item_error
            user_lbl = "A" if "내 동생은" in _section(prompt, "A") else "B"
            ai_lbl = "B" if user_lbl == "A" else "A"
            out = {
                "a_summary": "글 A는 주장을 제시한다.",
                "b_summary": "글 B는 근거를 활용한다.",
                "evidence": [
                    {"source": user_lbl, "sentence_id": 2, "reason": "개인 사례"},
                    {"source": ai_lbl, "sentence_id": 99, "reason": "범위 밖 번호"},
                ],
                "comparison": f"글 {user_lbl}는 경험에, {ai_lbl}는 통계에 기댄다.",
                "better": ai_lbl,
                "a_action": action if user_lbl == "A" else CLEAN_ACTION,
                "b_action": action if user_lbl == "B" else CLEAN_ACTION,
            }
            out["a_score"], out["b_score"] = (3, 4) if user_lbl == "A" else (4, 3)
            return out
        if title == "SummaryOutput":
            return {
                "overall_report": "두 글은 근거의 종류가 다릅니다. 내 글은 경험에 기대고 있습니다.",
                "strengths": ["자신의 경험을 근거로 삼았습니다."],
                "improvements": ["근거의 종류를 넓혀 보세요."],
                "questions": [
                    "이 문제에서 가장 중요하게 지켜야 할 가치는 무엇인가요?",
                    "반대 입장의 사람은 어떤 경험을 근거로 들까요?",
                    "규칙을 정하는 주체가 누구여야 한다고 생각하나요?",
                    "통계를 더 넣어야 하지 않을까요?",
                ],
            }
        if title == "QuestionCheckOutput":
            return {"verdicts": [{"index": i, "verdict": "open"} for i in range(3)]}
        if title == "ActionReviewOutput":
            return {"reviews": [{"key": k, "reflected": "yes", "reason": "근거를 추가했다."} for k in CRITERIA]}
        return "참고 초안 " + "가" * (900 if "다시 써라" in content else 300)

    return respond


@pytest.fixture
def client_factory(settings):
    clients = []

    def _make(responder):
        llm = FakeProvider(responder)
        client = TestClient(create_app(settings, llm))
        client.__enter__()
        clients.append(client)
        return client, llm

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def _wait(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/ai/jobs/{job_id}").json()
        if body["state"] in ("done", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError("job 시간 초과")


def _analyze(client):
    r = client.post("/ai/analyze", json={"topic": TOPIC, "user_draft": USER, "ai_draft": AI})
    assert r.status_code == 202
    return _wait(client, r.json()["job_id"])


def test_health(client_factory):
    client, _ = client_factory(scripted())
    assert client.get("/health").json()["llm"] == "up"


def test_analyze_end_to_end(client_factory):
    client, _ = client_factory(scripted())
    job = _analyze(client)
    assert job["state"] == "done"
    res = job["result"]
    assert res["status"] == "done"
    assert [it["key"] for it in res["items"]] == list(CRITERIA)
    item = res["items"][0]
    assert (item["user_score"], item["ai_score"], item["better"]) == (3, 4, "ai")
    # 문장 번호로 원문 인용을 채우고, 범위 밖 번호는 버린다
    assert item["evidence"] == [{"source": "user", "quote": "내 동생은 밤새 게임을 하다가 성적이 떨어졌다.", "reason": "개인 사례"}]
    # A/B 라벨은 사용자용 이름으로 바뀐다
    assert item["comparison"] == "내 글은 경험에, AI 글은 통계에 기댄다."
    # 유도 질문은 규칙 검사에서 빠지고 열린 질문 3개만 남는다
    assert len(res["questions"]) == 3 and all("않을까요" not in q for q in res["questions"])
    assert res["prompt_version"] == "v1" and res["model"] == "fake-llm"


def test_ghostwritten_action_item_is_retried_then_dropped(client_factory):
    copied = "일괄 수거는 자기 조절 능력을 기를 기회를 빼앗는다는 문장을 넣으세요."
    client, llm = client_factory(scripted(action=copied))
    res = _analyze(client)["result"]
    assert res["status"] == "partial"
    assert all(it["action_item"] is None for it in res["items"])
    assert len(llm.calls_for("ItemEvalOutput")) == 10  # 항목당 1회 재생성


def test_all_items_failing_fails_job(client_factory):
    client, _ = client_factory(scripted(item_error=LLMUnavailable("down")))
    job = _analyze(client)
    assert job["state"] == "failed"
    assert job["error"]["code"] == "LLM_UNAVAILABLE" and job["error"]["retryable"] is True


def test_reanalyze_keeps_ai_score_and_computes_delta(client_factory):
    client, _ = client_factory(scripted())
    prev = _analyze(client)["result"]
    for it in prev["items"]:
        it["user_score"], it["ai_score"] = 2, 5
    r = client.post(
        "/ai/reanalyze",
        json={
            "topic": TOPIC,
            "original_draft": USER,
            "current_draft": USER + " 통계청 자료도 함께 살펴보았다.",
            "ai_draft": AI,
            "previous_result": prev,
            "round": 2,
        },
    )
    res = _wait(client, r.json()["job_id"])["result"]
    assert all(it["ai_score"] == 5 for it in res["items"])
    assert res["score_delta"] == {k: 1 for k in CRITERIA}
    assert {x["reflected"] for x in res["action_item_review"]} == {"yes"}


def test_reference_draft_retries_on_length(client_factory):
    client, llm = client_factory(scripted())
    r = client.post("/ai/reference-draft", json={"topic": TOPIC, "requirements": {"length": "800~1000자"}})
    body = r.json()
    assert r.status_code == 200 and 800 <= body["char_count"] <= 1000
    assert body["warnings"] == [] and len(llm.calls) == 2


def test_error_format(client_factory, settings):
    client, _ = client_factory(scripted())
    r = client.post("/ai/analyze", json={"topic": " ", "user_draft": USER, "ai_draft": AI})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_INPUT"

    long_text = "가" * (settings.max_draft_chars + 1)
    r = client.post("/ai/analyze", json={"topic": TOPIC, "user_draft": long_text, "ai_draft": AI})
    assert r.status_code == 413 and r.json()["error"]["code"] == "INPUT_TOO_LONG"

    r = client.get("/ai/jobs/없는-작업")
    assert r.status_code == 404 and r.json()["error"]["code"] == "JOB_NOT_FOUND"
