"""API 명세를 docs/openapi.json으로 내보낸다. 백엔드·프론트 팀 공유용.

    python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> None:
    app = create_app(Settings(_env_file=None, warmup=False, llm_provider="mock"))
    out = ROOT / "docs" / "openapi.json"
    out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
