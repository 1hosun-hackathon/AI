from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM 제공자. mock이면 Ollama 없이 고정 형식의 가짜 응답을 낸다(연동 개발용).
    llm_provider: Literal["ollama", "mock"] = "ollama"
    mock_delay_sec: float = 0.0  # 가짜 응답마다 기다릴 시간(폴링 화면 확인용)

    # 공유 키. 설정하면 /health·문서 외 모든 요청에 X-API-Key 헤더가 이 값과 같아야 한다(외부 공개 시 필수).
    api_key: str | None = None
    public_docs: bool = False  # True면 키 없이도 /docs·/openapi.json을 연다(API_KEY가 없으면 항상 열림)
    rate_limit_per_min: int = 600  # IP별 분당 요청 수 (백엔드 서버 1대가 모든 사용자 요청을 보낸다는 전제)
    auth_fail_limit: int = 10  # 이 횟수만큼 틀린 키를 보내면
    auth_fail_window_sec: int = 600  # (이 시간 안에)
    auth_block_sec: int = 600  # 이 시간 동안 그 IP를 차단
    max_body_bytes: int = 1_000_000  # 일반 요청 본문 최대 크기
    max_upload_bytes: int = 52_000_000  # 첨부파일 경로(2-1) 본문 최대 크기 (10MB × 5 + 여유)

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "gemma4:e2b-it-qat"
    embed_model: str = "bge-m3"
    llm_think: Literal["true", "false", "omit"] = "false"
    llm_temperature: float = 0.0
    draft_temperature: float = 0.7
    llm_num_ctx: int = 8192
    llm_timeout_sec: float = 120.0
    llm_keep_alive: str = "30m"
    llm_concurrency: int = 1
    llm_seed: int = 42

    # 프롬프트·가드레일
    prompt_version: str = "v5"
    guardrail_max_retry: int = 1
    ngram_n: int = 12

    # 의존도
    ai_similar_threshold: float = 0.80
    keep_threshold: float = 0.75
    min_sentence_chars: int = 8

    # 입력·job
    max_draft_chars: int = 3000
    # 2-1 첨부파일에서 뽑아 AI 작성 글 프롬프트에 넣는 글자 수 합계 (파일 수로 나눠 배분, 0이면 반영 안 함)
    attachment_max_chars: int = 3000
    job_ttl_sec: int = 3600
    job_queue_max: int = 20
    warmup: bool = True

    @property
    def think_value(self) -> bool | None:
        """Ollama `think` 필드 값. None이면 필드를 보내지 않는다."""
        return {"true": True, "false": False, "omit": None}[self.llm_think]
