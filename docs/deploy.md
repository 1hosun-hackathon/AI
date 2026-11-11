# 배포: 개발 PC + 터널

AI 서버와 모델(Ollama)은 GPU가 있는 개발 PC에서 돌리고, 터널로 외부 주소를 연다. 비용이 들지 않고, 백엔드가 다른 네트워크(시연장 와이파이 등)에 있어도 인터넷만 되면 호출할 수 있다.

## 기본: ngrok 고정 주소 + 자동 시작

ngrok 무료 계정의 고정 도메인을 쓰므로 PC를 다시 켜도 주소가 바뀌지 않는다. 로그인하면 작업 스케줄러가 서버와 터널을 창 없이 켜고, 둘 중 하나가 꺼지면 30초 안에 다시 켠다.

### 처음 한 번

1. Ollama 설치 후 모델 받기: `ollama pull gemma4:e2b-it-qat`, `ollama pull bge-m3` (Ollama도 로그인 시 자동 실행되게 둔다)
2. 파이썬 환경: `python -m venv .venv` → `.venv\Scripts\pip install -e .`
3. ngrok 설치·로그인: `winget install --id Ngrok.Ngrok` → `ngrok update` → `ngrok config add-authtoken <대시보드의 토큰>`
4. `.env.example`을 `.env`로 복사하고 채운다.
   - `API_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   - `NGROK_DOMAIN`: ngrok 대시보드 > Domains의 도메인 (예: `xxxx.ngrok-free.dev`)
5. 자동 시작 등록: `powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1` → 지금 켜기: `Start-ScheduledTask -TaskName GeuljeokAI`
6. 절전 끄기(전원 연결 시): `powercfg /change standby-timeout-ac 0`, 시연 기간에는 Windows 업데이트 일시 중지

### 운영

- 상태 확인: `curl https://<도메인>/health` → `"llm": "up"`이면 정상
- 끄기/켜기: `Stop-ScheduledTask -TaskName GeuljeokAI` / `Start-ScheduledTask -TaskName GeuljeokAI`
- 자동 시작 해제: `powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Remove`
- 로그: `logs\server.log`(AI 서버), `logs
grok.log`, `logs\watchdog.log`(재시작 기록)
- 무료 ngrok은 월 1GB 전송 한도가 있다(분석 1회 수십 KB). 브라우저로 열면 경고 페이지가 먼저 뜨고, 그 페이지에 PC의 공인 IP가 표시된다.

## 대안: Cloudflare 빠른 터널 (계정 불필요, 주소가 매번 바뀜)

위 "처음 한 번"의 1·2·4(`API_KEY`만)·6번을 한 뒤, cloudflared를 설치한다: `winget install --id Cloudflare.cloudflared`

켤 때마다:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_public.ps1
```

- 창에 `https://<임의 이름>.trycloudflare.com` 주소가 나온다. 이 주소를 백엔드에 전달한다.
- **빠른 터널 주소는 켤 때마다 바뀐다.** 껐다 켜면 새 주소를 다시 알려 준다.
- 끌 때는 그 창에서 Ctrl+C.
- 상태 확인: 브라우저에서 `https://<주소>/health` → `"llm": "up"`이면 정상.

## 주의

- `API_KEY`는 저장소·공개 채널에 올리지 않는다. 백엔드 담당자에게 개인 메시지로 전달한다.
- 분석은 한 번에 하나씩 처리한다(1회 약 30~40초). 대기 중인 분석이 20건을 넘으면 `QUEUE_FULL`(429)을 돌려준다.
- 서버를 다시 켜면 진행 중이던 분석과 1시간 안의 결과가 사라진다. 백엔드는 `ANALYSIS_NOT_FOUND`를 받으면 같은 요청을 다시 보낸다.

## 백엔드 담당 (호출 쪽)

- 기본 주소: AI 담당에게 받은 주소 (설정값으로 두고 코드에 박지 않는다)
- 모든 요청에 헤더 두 개를 넣는다.
  - `X-API-Key: <받은 키>`: 없거나 틀리면 401 `UNAUTHORIZED`
  - `ngrok-skip-browser-warning: true`: ngrok 주소일 때 경고 페이지(HTML) 대신 API 응답을 받게 한다
- `/health`만 키 없이 열린다(키가 없으면 `{"status": "ok"}`만, 키가 있으면 모델·프롬프트 버전까지).
- API 문서는 저장소의 `docs/openapi.json`과 `docs/api.md`를 본다. 서버의 `/docs`는 외부 공개 시 닫혀 있다(`PUBLIC_DOCS=true`로 열 수 있다).
- 보호 장치: IP별 분당 600회를 넘으면 429 `RATE_LIMITED`. 틀린 키를 10분 안에 10번 보내면 그 IP를 10분 차단(429). 요청 본문은 1MB(2-1 첨부파일 경로는 52MB)까지.
- 호출 형식은 [api.md](api.md)의 "노션 API 명세 경로" 절을 따른다.
- 요청 제한 시간: 2-1(AI 작성 글 생성)은 동기 호출로 최대 1분 이상 걸릴 수 있으니 클라이언트 타임아웃을 120초 이상으로 둔다. 분석은 비동기(202)이고 4-1을 2초 간격으로 폴링한다.

## 비상용: 가짜 응답 모드

터널이나 PC에 문제가 생기면, 백엔드 쪽에서 이 저장소를 받아 모델 없이 띄울 수 있다. 화면 흐름은 그대로 동작하고 문장은 "가짜 응답:"으로 시작한다.

```bash
pip install -e .
LLM_PROVIDER=mock uvicorn app.main:app --port 8000
```
