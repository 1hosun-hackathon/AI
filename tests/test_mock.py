"""가짜 응답 모드(LLM_PROVIDER=mock): Ollama 없이 모든 엔드포인트가 정상 형식으로 응답해야 한다."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.common import CRITERIA
from tests.test_api import AI, TOPIC, USER, _wait


def test_mock_mode_serves_every_endpoint():
    settings = Settings(_env_file=None, warmup=False, llm_provider="mock")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["llm"] == "up"

        r = client.post("/ai/reference-draft", json={"topic": TOPIC, "requirements": {"length": "800~1000자"}})
        assert r.status_code == 200 and 800 <= r.json()["char_count"] <= 1000, r.json()

        r = client.post("/ai/analyze", json={"topic": TOPIC, "user_draft": USER, "ai_draft": AI})
        job = _wait(client, r.json()["job_id"])
        res = job["result"]
        assert res["status"] == "done", res["warnings"]
        assert res["model"] == "mock-llm"
        assert [it["key"] for it in res["items"]] == list(CRITERIA)
        assert all(it["action_item"] for it in res["items"]) and len(res["questions"]) == 3

        r = client.post(
            "/ai/reanalyze",
            json={
                "topic": TOPIC,
                "original_draft": USER,
                "current_draft": USER + " 통계청 자료도 함께 살펴보았다.",
                "ai_draft": AI,
                "previous_result": res,
                "round": 2,
            },
        )
        re_res = _wait(client, r.json()["job_id"])["result"]
        assert re_res["status"] == "done", re_res["warnings"]
        assert len(re_res["action_item_review"]) == len(CRITERIA)

        r = client.post("/ai/dependency", json={"user_draft": USER, "final_text": USER, "ai_draft": AI})
        assert r.status_code == 200, r.json()


def test_mock_mode_serves_backend_spec_endpoints():
    settings = Settings(_env_file=None, warmup=False, llm_provider="mock")
    task = {"topic": TOPIC, "writingType": "논설문", "requirements": "800~1,000자, 근거 2개 이상"}
    with TestClient(create_app(settings)) as client:
        r = client.post("/ai/v2/ai-writing", json=task)
        assert r.status_code == 200 and 800 <= r.json()["charCount"] <= 1000, r.json()

        r = client.post("/ai/v2/analyses", json={**task, "myWriting": {"content": USER}, "aiWriting": {"content": AI}})
        job_id = r.json()["jobId"]
        for _ in range(500):
            body = client.get(f"/ai/v2/analyses/{job_id}").json()
            if body["status"] in ("SUCCESS", "FAILED"):
                break
        assert body["status"] == "SUCCESS", body
        assert [it["criterion"] for it in body["result"]["items"]] == [k.upper() for k in CRITERIA]
