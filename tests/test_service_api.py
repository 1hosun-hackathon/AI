"""노션 API 명세 경로(/api/v1) 엔드포인트."""

import time

from app.llm.base import LLMUnavailable
from app.schemas.common import CRITERIA
from tests.test_api import AI, GOOD_QUESTIONS, TOPIC, USER, client_factory, scripted  # noqa: F401 - fixture 재사용

UPPER = [k.upper() for k in CRITERIA]
TASK = {"topic": TOPIC, "writingType": "논설문", "requirements": "800~1,000자, 근거 2개 이상"}
REVISED = USER + " 통계청 자료도 함께 살펴보았다."


def _wait(client, analysis_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/analyses/{analysis_id}/status").json()
        if body["status"] in ("SUCCESS", "FAILED"):
            return body
        assert body["status"] in ("PENDING", "GENERATING") and body["trainingStatus"] == "ANALYZING"
        time.sleep(0.02)
    raise AssertionError("분석 시간 초과")


def _draft(client, analysis_id=20):
    r = client.post(
        "/api/v1/trainings/12/draft",
        json={**TASK, "analysisId": analysis_id, "versionId": 30, "content": USER, "aiWriting": {"content": AI}},
    )
    assert r.status_code == 202, r.json()
    assert r.json() == {"versionId": 30, "seqNo": 0, "analysisId": analysis_id, "status": "ANALYZING"}
    return _wait(client, analysis_id)


def test_training_create_returns_ai_writing(client_factory):
    client, llm = client_factory(scripted())
    r = client.post("/api/v1/trainings", json={**TASK, "trainingId": 12})
    body = r.json()
    assert r.status_code == 201 and body["trainingId"] == 12
    assert 800 <= body["charCount"] <= 1000 and body["aiWriting"]["content"].startswith("참고 초안")
    prompt = llm.calls[0][0][1]["content"]
    assert "논설문" in prompt and "근거 2개 이상" in prompt


def test_draft_analysis_matches_spec(client_factory):
    client, _ = client_factory(scripted())
    status = _draft(client)
    assert status == {"analysisId": 20, "status": "SUCCESS", "trainingStatus": "COMPARED", "error": None}
    res = client.get("/api/v1/analyses/20").json()
    assert (res["analysisId"], res["trainingId"], res["seqNo"]) == (20, 12, 0)
    assert res["myWriting"] == {"versionId": 30, "content": USER} and res["aiWriting"] == {"content": AI}
    assert res["baseline"] is None and res["partial"] is False, res["warnings"]
    assert [it["criterion"] for it in res["items"]] == UPPER
    assert [(it["label"], it["description"]) for it in res["items"][:2]] == [("논지", "핵심 주장과 관점"), ("근거", "자료와 사례의 활용")]
    item = res["items"][0]
    assert (item["userScore"], item["aiScore"]) == (3, 4) and item["reflectPoint"]
    assert isinstance(res["strengths"], str) and isinstance(res["improvements"], str)
    assert res["questions"] == [{"seqNo": i, "content": q} for i, q in enumerate(GOOD_QUESTIONS, 1)]


def test_revision_uses_previous_result(client_factory):
    client, _ = client_factory(scripted())
    _draft(client)
    prev = client.get("/api/v1/analyses/20").json()
    for it in prev["items"]:
        it["userScore"] = 2
    body = {
        **TASK,
        "analysisId": 21,
        "versionId": 31,
        "seqNo": 1,
        "content": REVISED,
        "aiWriting": {"content": AI},
        "baseline": {"versionId": 30, "content": USER},
        "previousResult": prev,
    }
    r = client.post("/api/v1/trainings/12/revisions", json=body)
    assert r.status_code == 202 and r.json()["seqNo"] == 1
    assert _wait(client, 21)["status"] == "SUCCESS"
    res = client.get("/api/v1/analyses/21").json()
    assert res["seqNo"] == 1 and res["baseline"]["content"] == USER
    assert res["scoreDelta"] == {k: 1 for k in UPPER}
    assert {x["reflected"] for x in res["reflectionReviews"]} == {"yes"}

    r = client.post("/api/v1/trainings/12/revisions", json={**body, "analysisId": 22, "content": USER})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_CHANGES"


def test_failed_analysis_and_retry(client_factory):
    client, _ = client_factory(scripted(score_error=LLMUnavailable("down")))
    status = _draft(client)
    assert status["status"] == "FAILED" and status["error"]["code"] == "LLM_UNAVAILABLE"
    r = client.get("/api/v1/analyses/20")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ANALYSIS_NOT_READY"
    r = client.post("/api/v1/analyses/20/retry")
    assert r.status_code == 202 and r.json() == {"analysisId": 20, "status": "PENDING"}
    assert _wait(client, 20)["status"] == "FAILED"  # 모델이 계속 내려가 있으므로 다시 실패


def test_retry_only_when_failed_and_missing(client_factory):
    client, _ = client_factory(scripted())
    _draft(client)
    r = client.post("/api/v1/analyses/20/retry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ANALYSIS_NOT_FAILED"
    r = client.get("/api/v1/analyses/999/status")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_empty_content_rejected(client_factory):
    client, _ = client_factory(scripted())
    r = client.post(
        "/api/v1/trainings/12/draft", json={**TASK, "analysisId": 20, "content": "  ", "aiWriting": {"content": AI}}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "EMPTY_CONTENT"


def test_complete_returns_ratio_in_percent(client_factory):
    client, _ = client_factory(scripted())
    r = client.post(
        "/api/v1/trainings/12/complete",
        json={"content": USER, "draft": {"versionId": 30, "content": USER}, "aiWriting": {"content": AI}},
    )
    body = r.json()
    assert r.status_code == 200, body
    assert body["trainingId"] == 12 and body["status"] == "COMPLETED"
    assert body["selfThoughtRatio"] + body["aiDependencyRatio"] == 100.0 and body["sentences"]
