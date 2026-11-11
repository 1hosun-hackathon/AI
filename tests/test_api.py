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
STANCE_SHIFT = "자기 조절 교육이라는 반대 입장도 받아들여 절충해 보세요."  # 규칙으로 잡힘
SUBTLE_SHIFT = "스마트폰 사용의 교육적 장점을 결론에서 더 크게 다뤄 보세요."  # 규칙을 피해 LLM 판정으로 잡혀야 함
GOOD_QUESTIONS = [
    "이 문제에서 가장 중요하게 지켜야 할 가치는 무엇인가요?",
    "반대 입장의 사람은 어떤 경험을 근거로 들까요?",
    "규칙을 정하는 주체가 누구여야 한다고 생각하나요?",
]


def scripted(action=CLEAN_ACTION, improvements=None, score_error=None, shift_texts=()):
    """schema title로 호출 종류를 구분하는 가짜 LLM 응답."""

    def respond(messages, schema):
        title = (schema or {}).get("title")
        prompt = messages[1]["content"]
        if title in ("TextScoreOutput", "TextScoreWithActionOutput"):
            if score_error:
                raise score_error
            is_user = "내 동생은" in prompt
            out = {
                "summary": "이 글은 주장을 제시한다.",
                "evidence": [{"sentence_id": 2, "reason": "핵심 근거"}, {"sentence_id": 99, "reason": "범위 밖"}],
                "score": 3 if is_user else 4,
            }
            if title == "TextScoreWithActionOutput":
                out["action"] = action
            return out
        if title == "CompareOutput":
            first_is_user = prompt.index("내 동생은") < prompt.index("통계청")
            u, a = ("A", "B") if first_is_user else ("B", "A")
            return {"comparisons": [{"key": k, "comparison": f"글 {u}는 경험에, {a}는 통계에 기댄다."} for k in CRITERIA]}
        if title == "SummaryOutput":
            return {
                "overall_report": "두 글은 근거의 종류가 다릅니다. 내 글은 경험에 기대고 있습니다.",
                "strengths": ["자신의 경험을 근거로 삼았습니다."],
                "improvements": improvements or ["근거의 종류를 넓혀 보세요."],
                "questions": GOOD_QUESTIONS + ["통계를 더 넣어야 하지 않을까요?"],
            }
        if title == "FeedbackCheckOutput":
            entries = prompt.split("\n")
            verdicts = []
            for line in entries:
                if line[:1].isdigit() and ". (" in line:
                    idx = int(line.split(".")[0])
                    shift = any(t in line for t in shift_texts)
                    verdicts.append({"index": idx, "reason": "판정 이유", "verdict": "stance_shift" if shift else "ok"})
            return {"verdicts": verdicts}
        if title == "ActionReviewOutput":
            return {"reviews": [{"key": k, "reflected": "yes", "reason": "근거를 추가했다."} for k in CRITERIA]}
        content = messages[-1]["content"]
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
    client, llm = client_factory(scripted())
    job = _analyze(client)
    assert job["state"] == "done"
    res = job["result"]
    assert res["status"] == "done", res["warnings"]
    assert [it["key"] for it in res["items"]] == list(CRITERIA)
    item = res["items"][0]
    # 글마다 따로 채점하고, better는 점수로 정한다
    assert (item["user_score"], item["ai_score"], item["better"]) == (3, 4, "ai")
    assert len(llm.calls_for("TextScoreWithActionOutput")) == 5
    assert len(llm.calls_for("TextScoreOutput")) == 5
    # 채점 프롬프트에는 글이 한 편만 들어간다
    score_prompt = llm.calls_for("TextScoreOutput")[0][0][1]["content"]
    assert "통계청" in score_prompt and "내 동생은" not in score_prompt
    # 문장 번호로 원문 인용을 채우고, 범위 밖 번호는 버린다
    assert [(e["source"], e["quote"]) for e in item["evidence"]] == [
        ("user", "내 동생은 밤새 게임을 하다가 성적이 떨어졌다."),
        ("ai", "통계청 조사에 따르면 과의존 위험군이 많다."),
    ]
    # A/B 라벨은 사용자용 이름으로 바뀐다
    assert item["comparison"] == "내 글은 경험에, AI 글은 통계에 기댄다."
    # 유도 질문은 규칙 검사에서 빠지고 열린 질문 3개만 남는다
    assert res["questions"] == GOOD_QUESTIONS
    assert res["prompt_version"] == "v5" and res["model"] == "fake-llm"


def test_ghostwritten_action_item_is_retried_then_dropped(client_factory):
    copied = "일괄 수거는 자기 조절 능력을 기를 기회를 빼앗는다는 문장을 넣으세요."
    client, llm = client_factory(scripted(action=copied))
    res = _analyze(client)["result"]
    assert res["status"] == "partial"
    assert all(it["action_item"] is None for it in res["items"])
    assert len(llm.calls_for("TextScoreWithActionOutput")) == 10  # 항목당 1회 재생성
    assert any("참고 글과 겹치는 구절" in w for w in res["warnings"])


def test_explicit_stance_shift_is_caught_by_rule(client_factory):
    client, llm = client_factory(scripted(action=STANCE_SHIFT, improvements=[STANCE_SHIFT, "근거의 종류를 넓혀 보세요."]))
    res = _analyze(client)["result"]
    assert all(it["action_item"] is None for it in res["items"])
    assert len(llm.calls_for("TextScoreWithActionOutput")) == 10  # 규칙에 걸려 항목당 1회 재생성
    assert res["improvements"] == ["근거의 종류를 넓혀 보세요."]
    assert res["status"] == "partial"
    assert any("절충 권유" in w for w in res["warnings"])


def test_subtle_stance_shift_is_caught_by_llm_judge(client_factory):
    client, _ = client_factory(
        scripted(action=SUBTLE_SHIFT, improvements=[SUBTLE_SHIFT, "근거의 종류를 넓혀 보세요."], shift_texts=[SUBTLE_SHIFT])
    )
    res = _analyze(client)["result"]
    assert all(it["action_item"] is None for it in res["items"])
    assert res["improvements"] == ["근거의 종류를 넓혀 보세요."]
    assert any("결론·관점을 바꾸라고 권함" in w for w in res["warnings"])


def test_all_items_failing_fails_job(client_factory):
    client, _ = client_factory(scripted(score_error=LLMUnavailable("down")))
    job = _analyze(client)
    assert job["state"] == "failed"
    assert job["error"]["code"] == "LLM_UNAVAILABLE" and job["error"]["retryable"] is True


def test_reanalyze_keeps_ai_side_and_computes_delta(client_factory):
    client, llm = client_factory(scripted())
    prev = _analyze(client)["result"]
    for it in prev["items"]:
        it["user_score"], it["ai_score"], it["ai_summary"] = 2, 5, "이전 AI 요약"
    calls_before = len(llm.calls_for("TextScoreOutput"))
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
    assert all(it["ai_score"] == 5 and it["ai_summary"] == "이전 AI 요약" for it in res["items"])
    assert len(llm.calls_for("TextScoreOutput")) == calls_before  # AI 글은 다시 채점하지 않음
    assert res["score_delta"] == {k: 1 for k in CRITERIA}
    assert {x["reflected"] for x in res["action_item_review"]} == {"yes"}


def test_reference_draft_retries_on_length(client_factory):
    client, llm = client_factory(scripted())
    r = client.post("/ai/reference-draft", json={"topic": TOPIC, "requirements": {"length": "800~1000자"}})
    body = r.json()
    assert r.status_code == 200 and 800 <= body["char_count"] <= 1000
    drafts = [c for c in llm.calls if c[1] is None]  # 백그라운드 AI 글 미리 채점 호출은 빼고 센다
    assert body["warnings"] == [] and len(drafts) == 2


def test_error_format(client_factory, settings):
    client, _ = client_factory(scripted())
    r = client.post("/ai/analyze", json={"topic": " ", "user_draft": USER, "ai_draft": AI})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_INPUT"

    long_text = "가" * (settings.max_draft_chars + 1)
    r = client.post("/ai/analyze", json={"topic": TOPIC, "user_draft": long_text, "ai_draft": AI})
    assert r.status_code == 413 and r.json()["error"]["code"] == "INPUT_TOO_LONG"

    r = client.get("/ai/jobs/없는-작업")
    assert r.status_code == 404 and r.json()["error"]["code"] == "JOB_NOT_FOUND"
