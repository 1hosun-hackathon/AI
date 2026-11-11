"""API_KEY 설정 시 X-API-Key 헤더 검사."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KEY = "test-key-123"


def _client(**kw):
    return TestClient(create_app(Settings(_env_file=None, warmup=False, llm_provider="mock", **kw)))


def test_key_required_when_configured():
    with _client(api_key=KEY) as c:
        assert c.get("/health").status_code == 200  # 상태 확인은 키 없이
        assert c.get("/openapi.json").status_code == 200
        body = {"user_draft": "가나다라마바사.", "final_text": "가나다라마바사.", "ai_draft": "아자차카타파하."}
        r = c.post("/ai/dependency", json=body)
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
        r = c.post("/ai/dependency", json=body, headers={"X-API-Key": "wrong"})
        assert r.status_code == 401
        r = c.post("/ai/dependency", json=body, headers={"X-API-Key": KEY})
        assert r.status_code == 200
        r = c.get("/api/v1/analyses/1/status")
        assert r.status_code == 401  # 명세 경로도 같은 검사


def test_no_key_configured_keeps_api_open():
    with _client() as c:
        r = c.get("/api/v1/analyses/1/status")
        assert r.status_code == 404  # 키 검사 없이 바로 처리
