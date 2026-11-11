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

## 노션 API 명세 경로 (`/api/v1`, 백엔드 연동용)

노션 API 명세서의 AI 관련 API와 같은 경로·필드 이름이다. 백엔드는 자기 API를 처리하면서 같은 경로로 이 서버를 호출하면 된다. 아래 `/ai/...` 엔드포인트와 같은 파이프라인을 쓰며 형식만 다르다.

AI 서버는 훈련·글 버전을 저장하지 않으므로, 명세의 요청 본문에 **AI가 쓸 값**(과제 조건, AI 작성 글, 백엔드가 만든 `analysisId`)을 더해 보낸다.

| ID | 경로 | 방식 | AI 서버가 하는 일 |
|---|---|---|---|
| 2-1 | `POST /api/v1/trainings` | 동기 (수십 초) | AI 작성 글 생성. 첨부파일은 받기만 함 |
| 3-2 | `POST /api/v1/trainings/{trainingId}/draft` | 비동기 (202) | 초안 비교 분석 시작 |
| 3-4 | `POST /api/v1/trainings/{trainingId}/revisions` | 비동기 (202) | 수정본 재분석 + 지난 `reflectPoint` 반영 여부 |
| 3-5 | `POST /api/v1/trainings/{trainingId}/complete` | 동기, LLM 미사용 | 자기 사고 비율·AI 의존도(%) |
| 4-1 | `GET /api/v1/analyses/{analysisId}/status` | 동기, 2초 폴링 | 분석 상태 |
| 4-2 | `GET /api/v1/analyses/{analysisId}` | 동기 | 비교 분석 결과 |
| 4-3 | `GET /api/v1/trainings/{trainingId}/analyses` | 동기 | 회차별 분석 목록 |
| 4-4 | `POST /api/v1/analyses/{analysisId}/retry` | 비동기 (202) | 실패한 분석을 같은 입력으로 다시 실행. AI 작성 글이 없던 분석은 그것부터 생성 |

과제 조건 `{ "topic", "writingType", "requirements" }`는 2-1, 3-2, 3-4 요청에 training 값을 그대로 넣는다. `requirements` 문자열 안의 "800~1,000자", "1000자 이내", "500자 이상"을 분량으로 해석하고, 나머지 조건도 모델에 전달한다.

### 2-1 POST /api/v1/trainings

명세대로 `multipart/form-data`로 보낸다. `request` 파트(JSON)와 `files` 파트(0개 이상)로 구성하고, JSON 본문만 보내도 된다.

```json
// request 파트
{ "trainingId": 12, "topic": "기후변화와 탄소 중립 정책의 실효성", "writingType": "논설문",
  "requirements": "800~1,000자, 근거 2개 이상", "timerMinutes": 15 }
// 201 응답: aiWriting을 저장
{ "trainingId": 12, "aiWriting": { "content": "..." },
  "attachments": [ { "fileName": "IPCC_요약.pdf", "fileSize": 482113 } ],
  "charCount": 930, "warnings": [], "promptVersion": "v4", "model": "gemma4:e2b-it-qat" }
```

- 첨부파일은 형식·크기만 검사하고 AI 작성 글에는 반영하지 않는다. 허용 형식은 PDF·PPT(X)·DOC(X)·HWP(X)·TXT·MD·이미지(PNG, JPG, GIF, WEBP)다. 파일당 10MB, 5개까지 받는다.
- 형식이 맞지 않으면 400 `FILE_TYPE_NOT_ALLOWED`, 크기나 개수를 넘으면 413 `FILE_TOO_LARGE`.
- `startedAt`, `timerEndsAt`, `attachmentId`는 백엔드가 정하는 값이라 응답에 없다.
- 응답을 보낸 뒤 AI 서버가 백그라운드에서 AI 작성 글을 미리 채점한다(항목 5개). 3-2에서 같은 주제·같은 AI 글이 오면 이 결과를 써서 분석 시간이 줄어든다. 따라서 3-2에는 2-1에서 받은 `aiWriting`을 고치지 말고 그대로 보낸다.

### 3-2 POST /api/v1/trainings/{trainingId}/draft

```json
// 요청: 명세 본문 { content } + 과제 조건, analysisId, versionId, aiWriting(선택)
{ "topic": "...", "writingType": "논설문", "requirements": "...",
  "analysisId": 20, "versionId": 30, "content": "초안", "aiWriting": { "content": "AI 작성 글" } }
// 202 응답
{ "versionId": 30, "seqNo": 0, "analysisId": 20, "status": "ANALYZING" }
```

`aiWriting`이 없거나 비어 있으면(2-1 생성 실패) 분석 job이 AI 작성 글을 먼저 만든다. 만든 글은 4-2 `aiWriting`으로 돌려주므로 백엔드가 저장한다.

### 3-4 POST /api/v1/trainings/{trainingId}/revisions

```json
// 요청: 3-2 요청 + seqNo, baseline(최초 초안), previousResult(직전 회차 4-2 응답 그대로)
{ "topic": "...", "writingType": "논설문", "requirements": "...",
  "analysisId": 21, "versionId": 31, "seqNo": 1, "content": "수정본", "aiWriting": { "content": "..." },
  "baseline": { "versionId": 30, "content": "최초 초안" }, "previousResult": { /* 직전 4-2 응답 */ } }
// 202 응답
{ "versionId": 31, "seqNo": 1, "analysisId": 21, "status": "ANALYZING" }
```

- `content`가 `previousResult.myWriting.content`와 같으면 409 `NO_CHANGES`.
- `aiWriting`을 빼면 `previousResult.aiWriting`을 재사용한다(명세: "AI 작성 글은 재사용").

### 3-5 POST /api/v1/trainings/{trainingId}/complete

```json
// 요청: 명세 본문 { content } + 최초 초안, AI 작성 글
{ "content": "최종 글", "finalVersionId": 32, "draft": { "versionId": 30, "content": "최초 초안" }, "aiWriting": { "content": "..." } }
// 200 응답: 비율은 0~100 (소수 첫째 자리), 둘의 합은 100
{ "trainingId": 12, "status": "COMPLETED", "finalVersionId": 32, "completedAt": "2026-11-11T21:30:00+09:00", "selfThoughtRatio": 71.0, "aiDependencyRatio": 29.0,
  "sentences": [ { "text": "...", "label": "kept | new | ai_similar", "simUser": 0.82, "simAi": 0.41 } ],
  "method": "산정 기준 설명", "promptVersion": "v4", "model": "bge-m3" }
```

### 4-1 GET /api/v1/analyses/{analysisId}/status

```json
{ "analysisId": 20, "status": "PENDING | GENERATING | SUCCESS | FAILED", "trainingStatus": "ANALYZING | COMPARED", "error": null }
```

`FAILED`이면 `error`에 `{ "code", "message", "retryable" }`가 담긴다.

### 4-2 GET /api/v1/analyses/{analysisId}

```json
{
  "analysisId": 21, "trainingId": 12, "seqNo": 1, "createdAt": "2026-11-11T21:00:00+09:00",
  "myWriting": { "versionId": 31, "content": "..." }, "aiWriting": { "content": "..." },
  "baseline": { "versionId": 30, "content": "..." },
  "overallSummary": "종합 리포트 | null",
  "strengths": "강점 (여러 개면 줄바꿈으로 구분)",
  "improvements": "보완할 점 (여러 개면 줄바꿈으로 구분)",
  "items": [
    { "criterion": "THESIS", "label": "논지", "description": "핵심 주장과 관점",
      "userSummary": "...", "aiSummary": "...", "comparison": "...", "reflectPoint": "보완 방향 | null" }
  ],
  "questions": [ { "seqNo": 1, "content": "스스로 점검하는 질문" } ],
  // 여기부터 명세에 없는 필드
  "scores": [ { "criterion": "THESIS", "userScore": 3, "aiScore": 4, "better": "user | ai | tie",
                "evidence": [ { "source": "user | ai", "quote": "원문 문장", "reason": "..." } ] } ],
  "reflectionReviews": [ { "criterion": "THESIS", "reflectPoint": "...", "reflected": "yes | partial | no", "reason": "..." } ],
  "scoreDelta": { "THESIS": 1 },
  "partial": false, "warnings": [], "promptVersion": "v4", "model": "gemma4:e2b-it-qat"
}
```

- SUCCESS 전에는 409 `ANALYSIS_NOT_READY`.
- `items`는 THESIS(논지), EVIDENCE(근거), STRUCTURE(구조), EXPRESSION(표현), ORIGINALITY(독창성) 순서로 5개다.
- `items`는 명세 필드만 담는다. 점수는 명세대로 화면 응답에 넣지 않도록 `scores`로 분리했다.
- 명세에 없는 필드(`scores`, `reflectionReviews`, `scoreDelta`, `partial`, `warnings`, `promptVersion`, `model`)는 화면 응답에서 빼고, 응답 전체는 저장해 둔다. 대시보드(`mostImproved`, `focusArea`)는 `scores[].userScore`로 계산한다. 다시 검사할 때는 응답 전체를 `previousResult`로 그대로 보낸다.
- 결과는 AI 서버 메모리에 `JOB_TTL_SEC`(기본 1시간) 동안만 남는다. SUCCESS를 받으면 바로 가져가 저장한다.

### 4-3 GET /api/v1/trainings/{trainingId}/analyses

```json
[ { "analysisId": 20, "seqNo": 0, "status": "SUCCESS", "createdAt": "..." },
  { "analysisId": 21, "seqNo": 1, "status": "SUCCESS", "createdAt": "..." } ]
```

`seqNo` 오름차순이다. AI 서버 메모리에 남아 있는 분석(완료 후 1시간)만 나오므로, 오래된 회차는 백엔드 DB를 기준으로 한다.

### 4-4 POST /api/v1/analyses/{analysisId}/retry

```json
// 202 응답
{ "analysisId": 21, "status": "PENDING" }
```

FAILED인 분석만 가능하다(그 외 409 `ANALYSIS_NOT_FAILED`). 3-2/3-4에서 `aiWriting` 없이 시작한 분석이면 AI 작성 글부터 다시 만든다. 이미 만든 글이 있으면 그 글을 다시 쓴다. AI 서버가 재시작돼 분석을 잊었으면 404 `ANALYSIS_NOT_FOUND`이므로 3-2/3-4를 같은 `analysisId`로 다시 보낸다.

### 이 경로에서 추가로 쓰는 에러 코드

| code | HTTP | retryable | 의미 |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | false | 필수 필드 누락, 형식 오류 |
| `EMPTY_CONTENT` | 400 | false | 글 내용이 비어 있음 |
| `FILE_TYPE_NOT_ALLOWED` | 400 | false | 허용하지 않는 첨부파일 형식 |
| `FILE_TOO_LARGE` | 413 | false | 첨부파일 10MB 초과 또는 5개 초과 |
| `NO_CHANGES` | 409 | false | 직전 제출본과 같음 |
| `ANALYSIS_NOT_FOUND` | 404 | true | 분석 없음 (만료·재시작) |
| `ANALYSIS_NOT_READY` | 409 | true | 분석이 아직 끝나지 않음 |
| `ANALYSIS_NOT_FAILED` | 409 | false | 실패하지 않은 분석은 재시도 불가 |

`/api/v1` 경로의 형식 오류는 명세대로 400 `VALIDATION_ERROR`다. 기존 `/ai` 경로는 422 `INVALID_INPUT` 그대로다. 에러 본문 형식은 아래 [에러](#에러)와 같다.

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

`items[].key`는 바뀌지 않는다. 아래는 평가 기준 이름이다. `/api/v1` 응답의 `label`·`description`은 노션 명세 이름(논지·근거·구조·표현·독창성)을 쓴다. 평가는 내용 중립으로, 글의 결론이나 입장은 점수에 반영하지 않는다.

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
- 폴링 간격은 2~3초를 권장한다. 분석 1회는 개발 PC 기준 GPU(RTX 2060)에서 약 30~40초, GPU 없이 CPU(Ryzen 5 5600X)만 쓰면 약 2분 30초 걸린다(2-1 뒤 AI 글 미리 채점이 끝난 경우).

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
| `UNAUTHORIZED` | 401 | false | `X-API-Key` 헤더가 없거나 틀림 (`API_KEY` 설정 시) |
| `RATE_LIMITED` | 429 | true | 요청이 너무 많음, 또는 틀린 키 반복으로 잠시 차단 |

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
