"""reanalyze: analyze와 같은 흐름 + AI 점수 고정 + 점수 변화 + 지난 피드백 반영 여부."""

import logging

from app.llm.base import LLMError, Message
from app.llm.outputs import ActionReviewOutput
from app.llm.structured import generate_structured
from app.pipelines.analyze import assemble, build_feedback, evaluate_items
from app.pipelines.context import Ctx
from app.schemas.analysis import ActionItemReview, ItemResult, ReanalysisResult, ReanalyzeRequest
from app.schemas.common import CRITERIA_INFO
from app.text.diff import sentence_changes
from app.text.sentences import split_sentences

logger = logging.getLogger(__name__)


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- (없음)"


async def review_action_items(
    ctx: Ctx, req: ReanalyzeRequest, prev: dict[str, ItemResult], warnings: list[str]
) -> tuple[list[ActionItemReview], bool]:
    pending = [(k, it.action_item) for k, it in prev.items() if it.action_item]
    if not pending:
        return [], True

    removed, added = sentence_changes(split_sentences(req.original_draft), split_sentences(req.current_draft))
    if not removed and not added:
        return [ActionItemReview(key=k, action_item=a, reflected="no", reason="글이 바뀌지 않았습니다.") for k, a in pending], True

    changes = f"고치기 전 문장:\n{_bullets(removed)}\n고친 뒤 문장:\n{_bullets(added)}"
    action_items = "\n".join(f"- {k} ({CRITERIA_INFO[k][0]}): {a}" for k, a in pending)
    msgs: list[Message] = [
        {"role": "system", "content": ctx.prompts.raw("system")},
        {
            "role": "user",
            "content": ctx.prompts.render("action_review", topic=req.topic, action_items=action_items, changes=changes),
        },
    ]
    try:
        out = await generate_structured(ctx.llm, msgs, ActionReviewOutput, temperature=ctx.settings.llm_temperature)
    except LLMError as e:
        logger.warning("피드백 반영 판정 실패: %r", e)
        warnings.append("지난 피드백 반영 여부를 판정하지 못했습니다.")
        return [], False

    by_key = {r.key: r for r in out.reviews}
    reviews = [
        ActionItemReview(key=k, action_item=a, reflected=by_key[k].reflected, reason=by_key[k].reason)
        for k, a in pending
        if k in by_key
    ]
    if len(reviews) < len(pending):
        warnings.append("일부 피드백의 반영 여부를 판정하지 못했습니다.")
    return reviews, len(reviews) == len(pending)


async def run(ctx: Ctx, req: ReanalyzeRequest) -> ReanalysisResult:
    prev = {it.key: it for it in req.previous_result.items}
    comp = await evaluate_items(ctx, req.topic, req.requirements, req.current_draft, req.ai_draft)

    # AI 초안은 바뀌지 않으므로 다시 매긴 점수 대신 직전 점수를 쓴다 (노이즈 방지).
    for it in comp.items:
        if it.key in prev:
            it.ai_score = prev[it.key].ai_score

    score_delta: dict[str, int] = {}
    if req.previous_result.prompt_version == ctx.prompts.version:
        score_delta = {it.key: it.user_score - prev[it.key].user_score for it in comp.items if it.key in prev}
    else:
        comp.warnings.append("이전 결과와 평가 기준 버전이 달라 점수 변화를 계산하지 않았습니다.")

    reviews, reviews_ok = await review_action_items(ctx, req, prev, comp.warnings)
    fb = await build_feedback(ctx, req.topic, req.requirements, comp.items, req.current_draft, req.ai_draft)
    return ReanalysisResult(
        **assemble(ctx, comp, fb, extra_ok=reviews_ok), action_item_review=reviews, score_delta=score_delta
    )
