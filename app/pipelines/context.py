import random
from dataclasses import dataclass, field

from app.config import Settings
from app.llm.base import LLMProvider
from app.prompts.loader import Prompts


@dataclass
class Ctx:
    """파이프라인 공통 의존성. 요청마다 새로 만들 필요 없이 앱 시작 시 하나만 둔다."""

    llm: LLMProvider
    settings: Settings
    prompts: Prompts
    rng: random.Random = field(default_factory=random.Random)  # A/B 배정용

    def meta(self) -> dict[str, str]:
        return {"prompt_version": self.prompts.version, "model": self.llm.model_name}
