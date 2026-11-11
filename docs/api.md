# 글적글적 AI 서버 API 계약

백엔드가 호출하는 API의 계약이다. 정식 정의는 `app/schemas/`의 Pydantic 모델이며, 서버 실행 중에는 `/docs`(Swagger)에서도 볼 수 있다.

- 모든 요청·응답은 JSON, 문자 인코딩 UTF-8.
- 모든 성공 응답에 `prompt_version`, `model`이 들어간다.
- 글 한 편은 최대 3000자(`MAX_DRAFT_CHARS`).
- 기계가 읽는 명세는 `docs/openapi.json`이다(`python scripts/export_openapi.py`로 다시 만든다). 클라이언트 코드 생성이나 Postman 가져오기에 쓴다.

## 연동 개발용 가짜 응답 모드

Ollama·GPU 없이 API를 붙여 볼 수 있다. 문장 분리, 가드레일, job, 응답 조립은 실제 코드가 돌고 LLM 응답만 고정 문장으로 바뀐다.

```bash
LLM_PROVIDER=mock uvicorn app.main:app --port 8000
# job 폴링 화면을 확인하려면 호출마다 지연을 준다 (analyze 1건 ≈ LLM 13회)
LLM_PROVIDER=mock MOCK_DELAY_SEC=0.5 uvicorn app.main:app --port 8000
```

- 응답의 `model`이 `"mock-llm"`이고, 문장은 모두 "가짜 응답:"으로 시작한다.
- 점수는 입력 글의 해시로 정해져 같은 입력이면 같은 결과가 나온다(2~5점). 실제 평가 품질과는 관계없다.
- `/ai/dependency`는 원래 LLM을 쓰지 않지만, 가짜 모드에서는 임베딩도 글자 기반 가짜 벡터라 값이 실제와 다르다.

## 엔드포인트

| 메서드 | 경로 | 방식 | 설명 |
|---|---|---|---|
| GET | `/health` | 동기 | 서버·Ollama 상태 |
| POST | `/ai/reference-draft` | 동기 | AI 참고 초안 생성 (사용자 초안은 받지 않음) |
| POST | `/ai/analyze` | 비동기 (202 + `job_id`) | 초안 비교 분석 |
| POST | `/ai/reanalyze` | 비동기 (202 + `job_id`) | 다시 쓴 글 재분석 |
| GET | `/ai/jobs/{job_id}` | 동기 | job 상태·결과 조회 |
| POST | `/ai/dependency` | 동기 | AI 의존도 계산 (LLM 미사용) |

## 평가 항목 (화면 표시 이름)

`items[].key`는 바뀌지 않는다. 화면에는 key 대신 아래 이름을 표시한다. 평가는 내용 중립으로, 글의 결론이나 입장은 점수에 반영하지 않는다.

| key | 표시 이름 | 설명 |
|---|---|---|
| `thesis` | 목적·주제 설정 | 다루는 문제와 범위, 글의 목적이 분명한가 |
| `evidence` | 근거와 출처 | 주장마다 근거가 있고, 출처와 자기 해석이 구분되는가 |
| `structure` | 구성 | 서론·본론·결론의 역할과 문단 구성이 분명한가 |
| `expression` | 표현 | 문장이 정확하고 간결하며 용어가 일관된가 |
| `originality` | 논리 전개 | 비약 없이 이어지고 결론이 본론에서 도출되는가 |

v2까지 쓰던 이름(논지, 근거, 구조, 표현, 독창성)에서 바뀌었다. 특히 `originality`는 "독창성"이 아니라 "논리 전개"를 뜻한다.

## 공통 요청 필드: requirements

```json
{ "length": "800~1000자", "format": "논설문", "extra": null, "min_chars": 800, "max_chars": 1000 }
```

모두 선택. `min_chars`/`max_chars`는 추가 제안 필드로, 있으면 `length`보다 우선한다. 없으면 `length`의 "800~1000자", "1000자 이내", "500자 이상" 형식을 해석한다.

## job 조회 응답

```json
{ "job_id": "uuid", "state": "queued | running | done | failed", "result": { ... } | null, "error": { ... } | null }
```

- `state=done`: `result`에 분석 결과. `result.status`가 `partial`이면 일부 항목·필드가 빠진 것이고 사유는 `result.warnings`에 있다.
- `state=failed`: `error`에 공통 에러 본문.
- 완료된 job은 1시간 뒤 삭제된다. 서버가 재시작되면 진행 중인 job도 사라진다. `JOB_NOT_FOUND`를 받으면 같은 요청을 다시 보낸다.
- 폴링 간격은 2~3초를 권장한다. 분석 1회는 개발 PC(RTX 2060) 기준 약 40초 걸린다.

## 분석 결과에서 null이 될 수 있는 필드

| 필드 | null이 되는 경우 |
|---|---|
| `items[].action_item` | 보완 방향이 대필 검사를 끝까지 통과하지 못함 |
| `overall_report` | 종합 리포트가 대필 검사를 통과하지 못했거나 생성에 실패함 |

`strengths`, `improvements`, `questions`는 검사를 통과한 것만 담기므로 빈 배열일 수 있다.

## 재분석 요청 시 주의

- `previous_result`에는 직전 analyze 또는 reanalyze 결과를 그대로 넣는다.
- `ai_score`는 다시 매기지 않고 `previous_result`의 값을 쓴다.
- `previous_result.prompt_version`이 현재 서버와 다르면 `score_delta`는 빈 객체로 오고 `warnings`에 사유가 담긴다.

## 에러

```json
{ "error": { "code": "...", "message": "사용자에게 보여줄 수 있는 한국어 문구", "retryable": true } }
```

| code | HTTP | retryable | 의미 |
|---|---|---|---|
| `INVALID_INPUT` | 422 | false | 필수 필드 누락, 빈 글 |
| `INPUT_TOO_LONG` | 413 | false | 글이 최대 길이 초과 |
| `LLM_TIMEOUT` | 504 | true | 모델 응답 시간 초과 |
| `LLM_UNAVAILABLE` | 503 | true | Ollama 연결 실패 |
| `LLM_OUTPUT_INVALID` | 502 | true | 모델 출력 형식 오류 (재시도 후에도) |
| `GUARDRAIL_FAILED` | 502 | true | 출력이 가드레일을 통과하지 못함 |
| `JOB_NOT_FOUND` | 404 | true | job 없음 (만료·재시작). 같은 요청 재전송 |
| `QUEUE_FULL` | 429 | true | 대기 중인 분석이 너무 많음 |
| `INTERNAL` | 500 | true | 그 밖의 서버 오류 |

## 요청·응답 예시

정식 형식은 `docs/openapi.json`이다. 아래는 읽기 쉽게 줄인 예시다.

### POST /ai/reference-draft

```json
// 요청
{ "topic": "대학생 아르바이트가 학업에 미치는 영향", "requirements": { "format": "리포트", "length": "800~1000자" } }
// 응답
{ "draft": "string", "char_count": 950, "warnings": [], "prompt_version": "v4", "model": "gemma4:e2b-it-qat" }
```

### POST /ai/analyze (비동기)

```json
// 요청
{ "topic": "...", "requirements": { ... }, "user_draft": "...", "ai_draft": "..." }
// 응답 (202)
{ "job_id": "uuid" }
// GET /ai/jobs/{job_id}
{ "job_id": "...", "state": "queued | running | done | failed", "result": { ... } | null, "error": { ... } | null }
// state가 done일 때 result
{
  "status": "done | partial",
  "items": [
    {
      "key": "thesis",
      "user_score": 3, "ai_score": 4,
      "user_summary": "내 글의 해당 항목 요약",
      "ai_summary": "AI 글의 해당 항목 요약",
      "comparison": "두 글의 차이 설명",
      "evidence": [ { "source": "user | ai", "quote": "원문 그대로의 문장", "reason": "..." } ],
      "better": "user | ai | tie",
      "action_item": "보완 방향 (방향만, 고쳐 쓴 문장 없음) | null"
    }
  ],
  "overall_report": "종합 비교 리포트 (2~3문단) | null",
  "strengths": ["강점"],
  "improvements": ["보완할 점"],
  "questions": ["스스로 점검하는 열린 질문 2~3개"],
  "failed_items": [],
  "warnings": [],
  "prompt_version": "v4", "model": "gemma4:e2b-it-qat"
}
```

### POST /ai/reanalyze (비동기)

```json
// 요청
{ "topic": "...", "requirements": { ... }, "original_draft": "...", "current_draft": "...",
  "ai_draft": "...", "previous_result": { /* 직전 analyze 또는 reanalyze 결과 */ }, "round": 2 }
// result: analyze 결과 + 아래 필드
{
  "action_item_review": [ { "key": "thesis", "action_item": "...", "reflected": "yes | partial | no", "reason": "..." } ],
  "score_delta": { "thesis": 1, "evidence": 0, "structure": 1, "expression": 0, "originality": 0 }
}
```

### POST /ai/dependency (동기, LLM 미사용)

```json
// 요청
{ "user_draft": "...", "final_text": "...", "ai_draft": "..." }
// 응답
{
  "self_composition_ratio": 0.71,
  "ai_dependency_ratio": 0.29,
  "sentences": [ { "text": "...", "label": "kept | new | ai_similar", "sim_user": 0.82, "sim_ai": 0.41 } ],
  "method": { "embedding_model": "bge-m3", "ai_similar_threshold": 0.80, "keep_threshold": 0.75,
              "weighting": "chars", "description": "산정 기준 설명" }
}
```

## job 수명

- 서버 메모리에 저장하고, 끝난 job은 `JOB_TTL_SEC`(기본 3600초)가 지나면 지운다.
- 서버를 다시 시작하면 진행 중이던 job은 사라진다. `JOB_NOT_FOUND`(404, `retryable: true`)를 받으면 같은 요청을 다시 보낸다.
- 대기 중인 job이 `JOB_QUEUE_MAX`(기본 20)를 넘으면 `POST`는 429(`QUEUE_FULL`)로 거절한다.
- 서버는 uvicorn 워커 1개로 실행한다. 워커가 여러 개면 조회 요청이 다른 프로세스로 가서 job을 찾지 못한다.
