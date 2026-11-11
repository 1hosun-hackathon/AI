from typing import Annotated, Any, Literal

from pydantic import BaseModel, WithJsonSchema

JobState = Literal["queued", "running", "done", "failed"]


class JobCreated(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    job_id: str
    state: JobState
    # 실행 중에는 파이프라인 결과 dict를 그대로 돌려주고(분석 결과에 재분석 필드가 끼지 않게),
    # 명세(openapi.json)에는 두 결과 형식을 적는다. 두 모델은 app.main에서 components에 넣는다.
    result: Annotated[
        dict[str, Any] | None,
        WithJsonSchema(
            {
                "anyOf": [
                    {"$ref": "#/components/schemas/AnalysisResult"},
                    {"$ref": "#/components/schemas/ReanalysisResult"},
                    {"type": "null"},
                ],
                "description": "analyze job이면 AnalysisResult, reanalyze job이면 ReanalysisResult. state가 done일 때만 채워진다.",
            }
        ),
    ] = None
    error: dict[str, Any] | None = None  # {"code", "message", "retryable"}
