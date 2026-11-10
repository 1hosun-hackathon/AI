import re
from pathlib import Path
from string import Template

_BASE = Path(__file__).parent
_SECTION = re.compile(r"^##\s+(\w+)\s*$", re.M)


class Prompts:
    """app/prompts/{version}/*.md 를 읽어 string.Template으로 채운다."""

    def __init__(self, version: str, base_dir: Path = _BASE):
        self.version = version
        self.dir = base_dir / version
        if not self.dir.is_dir():
            raise FileNotFoundError(f"프롬프트 버전 디렉토리가 없습니다: {self.dir}")
        self._cache: dict[str, str] = {}
        self._rubric = self._parse_sections(self.raw("rubric"))

    def raw(self, name: str) -> str:
        if name not in self._cache:
            self._cache[name] = (self.dir / f"{name}.md").read_text(encoding="utf-8").strip()
        return self._cache[name]

    def render(self, template: str, /, **values: object) -> str:
        # template은 위치 전용: 템플릿 변수 이름(name 등)과 겹치지 않게 한다.
        return Template(self.raw(template)).substitute(**{k: str(v) for k, v in values.items()})

    def rubric(self, key: str) -> str:
        return self._rubric[key]

    @staticmethod
    def _parse_sections(text: str) -> dict[str, str]:
        parts = _SECTION.split(text)
        # parts = [머리말, key1, body1, key2, body2, ...]
        return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
