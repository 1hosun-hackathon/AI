# 배포: 개발 PC + Cloudflare 터널

AI 서버와 모델(Ollama)은 GPU가 있는 개발 PC에서 돌리고, Cloudflare 빠른 터널로 외부 주소를 연다. 비용이 들지 않고, 백엔드가 다른 네트워크(시연장 와이파이 등)에 있어도 인터넷만 되면 호출할 수 있다.

## AI 담당 (PC 쪽)

### 처음 한 번

1. Ollama 설치 후 모델 받기: `ollama pull gemma4:e2b-it-qat`, `ollama pull bge-m3`
2. 파이썬 환경: `python -m venv .venv` → `.venv\Scripts\pip install -e .`
3. cloudflared 설치: `winget install --id Cloudflare.cloudflared`
4. `.env.example`을 `.env`로 복사하고 `API_KEY`를 채운다.
   키 만들기: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
5. 서버를 켜 둘 동안 PC가 잠들지 않게 한다.
   - 절전 끄기(전원 연결 시): `powercfg /change standby-timeout-ac 0`
   - Windows 업데이트: 설정 > Windows 업데이트 > 업데이트 일시 중지 (시연 기간 동안)

### 켤 때마다

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_public.ps1
```

- 창에 `https://<임의 이름>.trycloudflare.com` 주소가 나온다. 이 주소를 백엔드에 전달한다.
- **빠른 터널 주소는 켤 때마다 바뀐다.** 껐다 켜면 새 주소를 다시 알려 준다.
- 끌 때는 그 창에서 Ctrl+C.
- 상태 확인: 브라우저에서 `https://<주소>/health` → `"llm": "up"`이면 정상.

### 주의

- `API_KEY`는 저장소·공개 채널에 올리지 않는다. 백엔드 담당자에게 개인 메시지로 전달한다.
- 분석은 한 번에 하나씩 처리한다(1회 약 30~40초). 대기 중인 분석이 20건을 넘으면 `QUEUE_FULL`(429)을 돌려준다.
- 서버를 다시 켜면 진행 중이던 분석과 1시간 안의 결과가 사라진다. 백엔드는 `ANALYSIS_NOT_FOUND`를 받으면 같은 요청을 다시 보낸다.

## 백엔드 담당 (호출 쪽)

- 기본 주소: AI 담당에게 받은 `https://<임의 이름>.trycloudflare.com` (설정값으로 두고 코드에 박지 않는다)
- 모든 요청에 헤더 `X-API-Key: <받은 키>`를 넣는다. 없거나 틀리면 401 `UNAUTHORIZED`.
- `/health`와 API 문서(`/docs`, `/openapi.json`)는 키 없이 열린다. `/docs`에서 Authorize 버튼에 키를 넣으면 바로 호출해 볼 수 있다.
- 호출 형식은 [api.md](api.md)의 "노션 API 명세 경로" 절을 따른다.
- 요청 제한 시간: 2-1(AI 작성 글 생성)은 동기 호출로 최대 1분 이상 걸릴 수 있으니 클라이언트 타임아웃을 120초 이상으로 둔다. 분석은 비동기(202)이고 4-1을 2초 간격으로 폴링한다.

## 비상용: 가짜 응답 모드

터널이나 PC에 문제가 생기면, 백엔드 쪽에서 이 저장소를 받아 모델 없이 띄울 수 있다. 화면 흐름은 그대로 동작하고 문장은 "가짜 응답:"으로 시작한다.

```bash
pip install -e .
LLM_PROVIDER=mock uvicorn app.main:app --port 8000
```
