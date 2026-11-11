import pytest

from app.config import Settings
from app.pipelines.context import Ctx
from app.prompts.loader import Prompts
from tests.fakes import FakeProvider


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, warmup=False)


@pytest.fixture
def make_ctx(settings):
    def _make(responder=None) -> Ctx:
        return Ctx(llm=FakeProvider(responder), settings=settings, prompts=Prompts(settings.prompt_version))

    return _make
