"""외부 공개 대비 요청 검사: API 키, 반복 실패 차단, 요청 수·본문 크기 제한, 공개 정보 최소화."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KEY = "test-key-123"
H = {"X-API-Key": KEY}
BODY = {"user_draft": "가나다라마바사.", "final_text": "가나다라마바사.", "ai_draft": "아자차카타파하."}


def _client(**kw):
    return TestClient(create_app(Settings(_env_file=None, warmup=False, llm_provider="mock", **kw)))


def test_key_required_when_configured():
    with _client(api_key=KEY) as c:
        r = c.post("/ai/dependency", json=BODY)
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
        assert c.post("/ai/dependency", json=BODY, headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.post("/ai/dependency", json=BODY, headers=H).status_code == 200
        assert c.get("/api/v1/analyses/1/status").status_code == 401  # 명세 경로도 같은 검사


def test_public_info_is_minimal_without_key():
    with _client(api_key=KEY) as c:
        assert c.get("/health").json() == {"status": "ok"}  # 키 없이: 정상 여부만
        assert "model" in c.get("/health", headers=H).json()  # 키 있으면: 모델·버전까지
        assert c.get("/openapi.json").status_code == 401  # 문서는 키가 있어야 본다
        assert c.get("/docs").status_code == 401
        assert c.get("/openapi.json", headers=H).status_code == 200
    with _client(api_key=KEY, public_docs=True) as c:
        assert c.get("/openapi.json").status_code == 200


def test_repeated_wrong_keys_block_the_ip():
    with _client(api_key=KEY, auth_fail_limit=3) as c:
        for _ in range(3):
            assert c.post("/ai/dependency", json=BODY, headers={"X-API-Key": "guess"}).status_code == 401
        r = c.post("/ai/dependency", json=BODY, headers=H)  # 맞는 키여도 차단 중
        assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_block_uses_forwarded_ip_from_the_tunnel():
    """터널 뒤에서는 X-Forwarded-For의 IP별로 따로 센다(루프백에서 온 요청만 믿는다)."""
    with _client(api_key=KEY, auth_fail_limit=2) as c:
        c.app.state  # noqa: B018 - 앱 시작
        for _ in range(2):
            c.post("/ai/dependency", json=BODY, headers={"X-API-Key": "guess", "X-Forwarded-For": "1.2.3.4"})
        # TestClient의 접속 주소는 루프백이 아니므로 X-Forwarded-For를 무시하고 접속 주소로 센다
        assert c.post("/ai/dependency", json=BODY, headers=H).status_code == 429


def test_rate_limit_and_body_size():
    with _client(api_key=KEY, rate_limit_per_min=3) as c:
        codes = [c.get("/health").status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
    with _client(api_key=KEY, max_body_bytes=100) as c:
        r = c.post("/ai/dependency", json={**BODY, "final_text": "가" * 200}, headers=H)
        assert r.status_code == 413 and r.json()["error"]["code"] == "INPUT_TOO_LONG"


def test_no_key_configured_keeps_api_open():
    with _client() as c:
        assert c.get("/api/v1/analyses/1/status").status_code == 404  # 키 검사 없이 바로 처리
        assert "model" in c.get("/health").json()
        assert c.get("/openapi.json").status_code == 200
