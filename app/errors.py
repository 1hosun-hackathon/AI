"""서비스 공통 에러. 응답 형식: {"error": {"code", "message", "retryable"}}"""

# code: (HTTP 상태, 재시도 가능 여부, 사용자 노출 문구)
ERRORS: dict[str, tuple[int, bool, str]] = {
    "INVALID_INPUT": (422, False, "입력값을 확인해 주세요."),
    "INPUT_TOO_LONG": (413, False, "글이 너무 길어요. 분량을 줄여 다시 시도해 주세요."),
    "LLM_TIMEOUT": (504, True, "AI 응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요."),
    "LLM_UNAVAILABLE": (503, True, "AI 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요."),
    "LLM_OUTPUT_INVALID": (502, True, "AI 응답을 처리하지 못했어요. 다시 시도해 주세요."),
    "GUARDRAIL_FAILED": (502, True, "AI 피드백이 검사 기준을 통과하지 못했어요. 다시 시도해 주세요."),
    "JOB_NOT_FOUND": (404, True, "분석 작업을 찾을 수 없어요. 다시 요청해 주세요."),
    "QUEUE_FULL": (429, True, "요청이 많아 잠시 후 다시 시도해 주세요."),
    "INTERNAL": (500, True, "일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요."),
}


class AppError(Exception):
    def __init__(self, code: str, message: str | None = None, detail: str | None = None):
        status, retryable, default_message = ERRORS[code]
        self.code = code
        self.status = status
        self.retryable = retryable
        self.message = message or default_message
        self.detail = detail  # 로그용, 응답에는 넣지 않음
        super().__init__(f"{code}: {detail or self.message}")

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}
