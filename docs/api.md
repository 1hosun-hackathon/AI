# 글적글적 AI 서버 API 계약

백엔드가 호출하는 API의 계약이다. 정식 정의는 `app/schemas/`의 Pydantic 모델이며, 서버 실행 중에는 `/docs`(Swagger)에서도 볼 수 있다.

- 모든 요청·응답은 JSON, 문자 인코딩 UTF-8.
- 모든 성공 응답에 `prompt_version`, `model`이 들어간다.
- 글 한 편은 최대 3000자(`MAX_DRAFT_CHARS`).

## 엔드포인트

| 메서드 | 경로 | 방식 | 설명 |
|---|---|---|---|
| GET | `/health` | 동기 | 서버·Ollama 상태 |
| POST | `/ai/reference-draft` | 동기 | AI 참고 초안 생성 (사용자 초안은 받지 않음) |
| POST | `/ai/analyze` | 비동기 (202 + `job_id`) | 초안 비교 분석 |
| POST | `/ai/reanalyze` | 비동기 (202 + `job_id`) | 다시 쓴 글 재분석 |
| GET | `/ai/jobs/{job_id}` | 동기 | job 상태·결과 조회 |
| POST | `/ai/dependency` | 동기 | AI 의존도 계산 (LLM 미사용) |

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

