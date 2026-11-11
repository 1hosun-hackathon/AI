"""백엔드 API 명세 형식(/ai/v2) 엔드포인트."""

import time

from app.schemas.common import CRITERIA
from tests.test_api import AI, GOOD_QUESTIONS, TOPIC, USER, client_factory, scripted  # noqa: F401 - fixture 재사용

UPPER = [k.upper() for k in CRITERIA]
TASK = {"topic": TOPIC, "writingType": "논설문", "requirements": "800~1,000자, 근거 2개 이상"}


def _wait(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/ai/v2/analyses/{job_id}").json()
        if body["status"] in ("SUCCESS", "FAILED"):
            return body
        assert body["status"] in ("PENDING", "GENERATING")
        time.sleep(0.02)
    raise AssertionError("job 시간 초과")


def _first(client):
    r = client.post("/ai/v2/analyses", json={**TASK, "seqNo": 0, "myWriting": {"content": USER}, "aiWriting": {"content": AI}})
    assert r.status_code == 202 and r.json()["status"] == "PENDING"
    return _wait(client, r.json()["jobId"])


def test_ai_writing_parses_requirement_string(client_factory):
    client, llm = client_factory(scripted())
    r = client.post("/ai/v2/ai-writing", json=TASK)
    body = r.json()
    assert r.status_code == 200 and 800 <= body["charCount"] <= 1000, body
    assert body["content"].startswith("참고 초안") and body["promptVersion"] == "v4"
    prompt = llm.calls[0][0][1]["content"]
    assert "논설문" in prompt and "근거 2개 이상" in prompt


def test_analysis_matches_spec_shape(client_factory):
    client, _ = client_factory(scripted())
    job = _first(client)
    assert job["status"] == "SUCCESS" and job["error"] is None
    res = job["result"]
    assert res["seqNo"] == 0 and res["partial"] is False, res["warnings"]
    assert [it["criterion"] for it in res["items"]] == UPPER
    item = res["items"][0]
    assert (item["label"], item["userScore"], item["aiScore"]) == ("목적·주제 설정", 3, 4)
    assert item["reflectPoint"] and item["comparison"].startswith("내 글은")
    assert isinstance(res["strengths"], str) and isinstance(res["improvements"], str)
    assert res["questions"] == [{"seqNo": i, "content": q} for i, q in enumerate(GOOD_QUESTIONS, 1)]
    assert res["reflectionReviews"] == [] and res["scoreDelta"] == {}


def test_recheck_uses_previous_result(client_factory):
    client, _ = client_factory(scripted())
    prev = _first(client)["result"]
    for it in prev["items"]:
        it["userScore"] = 2
    r = client.post(
        "/ai/v2/analyses",
        json={
            **TASK,
            "seqNo": 1,
            "myWriting": {"content": USER + " 통계청 자료도 함께 살펴보았다."},
            "aiWriting": {"content": AI},
            "baseline": {"content": USER},
            "previousResult": prev,
        },
    )
    assert r.status_code == 202
    res = _wait(client, r.json()["jobId"])["result"]
    assert res["seqNo"] == 1
    assert res["scoreDelta"] == {k: 1 for k in UPPER}
    assert [x["criterion"] for x in res["reflectionReviews"]] == UPPER
    assert {x["reflected"] for x in res["reflectionReviews"]} == {"yes"}


def test_recheck_requires_baseline_and_previous(client_factory):
    client, _ = client_factory(scripted())
    r = client.post("/ai/v2/analyses", json={**TASK, "seqNo": 1, "myWriting": {"content": USER}, "aiWriting": {"content": AI}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_INPUT"


def test_failed_job_and_missing_job(client_factory):
    from app.llm.base import LLMUnavailable

    client, _ = client_factory(scripted(score_error=LLMUnavailable("down")))
    job = _first(client)
    assert job["status"] == "FAILED" and job["error"]["code"] == "LLM_UNAVAILABLE"
    r = client.get("/ai/v2/analyses/없는-작업")
    assert r.status_code == 404 and r.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_self_thought_ratio_in_percent(client_factory):
    client, _ = client_factory(scripted())
    r = client.post(
        "/ai/v2/self-thought-ratio",
        json={"draft": {"content": USER}, "finalWriting": {"content": USER}, "aiWriting": {"content": AI}},
    )
    body = r.json()
    assert r.status_code == 200, body
    assert body["selfThoughtRatio"] + body["aiDependencyRatio"] == 100.0
    assert 0 <= body["selfThoughtRatio"] <= 100 and body["sentences"]
