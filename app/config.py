from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    prompt_version: str = "v3"
    guardrail_max_retry: int = 1
    ngram_n: int = 12

    # 의존도
    ai_similar_threshold: float = 0.80
    keep_threshold: float = 0.75
    min_sentence_chars: int = 8

    # 입력·job
    max_draft_chars: int = 3000
    job_ttl_sec: int = 3600
    job_queue_max: int = 20
    warmup: bool = True

    @property
    def think_value(self) -> bool | None:
        """Ollama `think` 필드 값. None이면 필드를 보내지 않는다."""
        return {"true": True, "false": False, "omit": None}[self.llm_think]
