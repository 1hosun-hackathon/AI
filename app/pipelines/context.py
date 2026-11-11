import asyncio
import random
from collections import OrderedDict
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
    # AI 작성 글 채점 결과(미리 채점). 키는 analyze.ai_score_key, 값은 채점 task. 관리는 app.pipelines.analyze가 한다.
    ai_scores: "OrderedDict[str, asyncio.Task]" = field(default_factory=OrderedDict)

    def meta(self) -> dict[str, str]:
        return {"prompt_version": self.prompts.version, "model": self.llm.model_name}
