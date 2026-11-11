# AI

글적글적 AI 서버. 학습자 글과 AI 작성 글을 비교 분석하고 피드백을 만든다. 모델은 로컬 Ollama(gemma4:e2b-it-qat, bge-m3)로 돌린다.

- API 계약: [docs/api.md](docs/api.md) (백엔드 연동은 "노션 API 명세 경로" 절), 기계용 명세: [docs/openapi.json](docs/openapi.json)
- 배포·외부 공개(PC + ngrok 고정 주소): [docs/deploy.md](docs/deploy.md)

## 로컬 실행

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # macOS/Linux: .venv/bin/pip
cp .env.example .env
uvicorn app.main:app --port 8000
```

- 모델 없이 연동만 확인할 때: `LLM_PROVIDER=mock uvicorn app.main:app --port 8000`
- 테스트: `pytest -q`
