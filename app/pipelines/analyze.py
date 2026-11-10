"""analyze: 항목 평가 5회 → 인용 채우기 → 종합 피드백 → 가드레일 → 조립."""

import asyncio
import logging
from dataclasses import dataclass, field

from app.errors import AppError
from app.guardrails.citation import resolve_evidence
from app.guardrails.ghostwriting import ghostwriting_issues
from app.guardrails.questions import rule_check_question
from app.llm.base import LLMError, Message
from app.llm.outputs import ItemEvalOutput, QuestionCheckOutput, SummaryOutput
from app.llm.structured import generate_structured
from app.pipelines.context import Ctx
from app.schemas.analysis import AnalysisResult, AnalyzeRequest, ItemResult
from app.schemas.common import CRITERIA, CRITERIA_INFO, Requirements
from app.text.labels import relabel
from app.text.sentences import numbered, split_sentences

logger = logging.getLogger(__name__)

USER_NAME, AI_NAME = "내 글", "AI 글"


@dataclass
class Comparison:
    items: list[ItemResult]
    failed: list[str]
    warnings: list[str]


@dataclass
class Feedback:
    overall_report: str | None = None
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    complete: bool = False


class _Checker:
    """대필 검사 공통 설정 (참고 글, 주제·요구사항 제외, 학습자 글 인용 허용)."""

    def __init__(self, ctx: Ctx, topic: str, req: Requirements, user_text: str, ai_text: str):
        self.n = ctx.settings.ngram_n
        self.ai_text = ai_text
        self.exclude = [topic, req.format or "", req.extra or "", req.length or ""]
        self.allowed = [user_text]

    def __call__(self, text: str) -> list[str]:
        return ghostwriting_issues(
            text, self.ai_text, n=self.n, exclude=self.exclude, allowed_quote_sources=self.allowed
        )


def _system(ctx: Ctx) -> Message:
    return {"role": "system", "content": ctx.prompts.raw("system")}


def _retry_note(ctx: Ctx, problems: list[str]) -> Message:
    return {"role": "user", "content": ctx.prompts.render("guardrail_retry", problems="\n".join(f"- {p}" for p in problems))}


# ---------------------------------------------------------------- 항목 평가


async def evaluate_items(
    ctx: Ctx, topic: str, req: Requirements, user_text: str, ai_text: str
) -> Comparison:
    s = ctx.settings
    user_s, ai_s = split_sentences(user_text), split_sentences(ai_text)
    user_is_a = ctx.rng.random() < 0.5  # 위치 편향 완화: 매번 무작위 배정
    sents = {"A": user_s, "B": ai_s} if user_is_a else {"A": ai_s, "B": user_s}
    to_src = {"A": "user", "B": "ai"} if user_is_a else {"A": "ai", "B": "user"}
    names = {lbl: USER_NAME if src == "user" else AI_NAME for lbl, src in to_src.items()}
    user_lbl = "a" if user_is_a else "b"
    ai_lbl = "b" if user_is_a else "a"
    check = _Checker(ctx, topic, req, user_text, ai_text)
    warnings: list[str] = []

    async def one(key: str) -> ItemResult:
        name, desc = CRITERIA_INFO[key]
        msgs: list[Message] = [
            _system(ctx),
            {
                "role": "user",
                "content": ctx.prompts.render(
                    "item_eval",
                    topic=topic,
                    name=name,
                    description=desc,
                    rubric=ctx.prompts.rubric(key),
                    text_a=numbered(sents["A"]),
                    text_b=numbered(sents["B"]),
                ),
            },
        ]
        out = await generate_structured(ctx.llm, msgs, ItemEvalOutput, temperature=s.llm_temperature)
        action = relabel(getattr(out, f"{user_lbl}_action"), names)
        issues = check(action)
        for _ in range(s.guardrail_max_retry):
            if not issues:
                break
            retry = msgs + [{"role": "assistant", "content": out.model_dump_json()}, _retry_note(ctx, issues)]
            out = await generate_structured(ctx.llm, retry, ItemEvalOutput, temperature=s.llm_temperature)
            action = relabel(getattr(out, f"{user_lbl}_action"), names)
            issues = check(action)
        if issues:
            warnings.append(f"{name}: 보완 방향이 대필 검사를 통과하지 못해 제외했습니다.")

        return ItemResult(
            key=key,
            user_score=getattr(out, f"{user_lbl}_score"),
            ai_score=getattr(out, f"{ai_lbl}_score"),
            user_summary=relabel(getattr(out, f"{user_lbl}_summary"), names),
            ai_summary=relabel(getattr(out, f"{ai_lbl}_summary"), names),
            comparison=relabel(out.comparison, names),
            evidence=[
                e.model_copy(update={"reason": relabel(e.reason, names)})
                for e in resolve_evidence(out.evidence, sents, to_src)
            ],
            better="tie" if out.better == "tie" else to_src[out.better],
            action_item=None if issues else action,
        )

    results = await asyncio.gather(*(one(k) for k in CRITERIA), return_exceptions=True)
    items: list[ItemResult] = []
    failed: list[str] = []
    errors: list[BaseException] = []
    for key, r in zip(CRITERIA, results):
        if isinstance(r, BaseException):
            logger.warning("항목 %s 평가 실패: %r", key, r)
            failed.append(key)
            errors.append(r)
        else:
            items.append(r)
    if not items:
        first = errors[0]
        if isinstance(first, (AppError, LLMError)):
            raise first
        raise AppError("INTERNAL", detail=repr(first))
    return Comparison(items=items, failed=failed, warnings=warnings)


# ---------------------------------------------------------------- 종합 피드백


def _item_lines(items: list[ItemResult]) -> str:
    lines = []
    for it in items:
        name = CRITERIA_INFO[it.key][0]
        lines.append(
            f"- {name}: 학습자 {it.user_score}점 / AI {it.ai_score}점\n"
            f"  학습자 글: {it.user_summary}\n  AI 글: {it.ai_summary}\n  비교: {it.comparison}"
        )
    return "\n".join(lines)


async def _check_questions(ctx: Ctx, candidates: list[str], warnings: list[str]) -> list[str]:
    if not candidates:
        return []
    listing = "\n".join(f"{i}. {q}" for i, q in enumerate(candidates))
    msgs: list[Message] = [
        _system(ctx),
        {"role": "user", "content": ctx.prompts.render("question_check", questions=listing)},
    ]
    try:
        out = await generate_structured(ctx.llm, msgs, QuestionCheckOutput, temperature=0.0)
    except LLMError as e:
        logger.warning("질문 판정 실패: %r", e)
        warnings.append("질문 열린 정도 판정을 건너뛰었습니다.")
        return candidates
    leading = {v.index for v in out.verdicts if v.verdict == "leading"}
    return [q for i, q in enumerate(candidates) if i not in leading]


async def _filter_feedback(ctx: Ctx, out: SummaryOutput, check: _Checker) -> tuple[list[str], Feedback]:
    problems: list[str] = []
    fb = Feedback()

    report_issues = check(out.overall_report)
    if report_issues:
        problems.append(f"종합 리포트: {', '.join(report_issues)}")
    else:
        fb.overall_report = out.overall_report

    for field_name, label in (("strengths", "강점"), ("improvements", "보완할 점")):
        kept = []
        for text in getattr(out, field_name):
            issues = check(text)
            if issues:
                problems.append(f"{label} '{text[:20]}…': {', '.join(issues)}")
            else:
                kept.append(text)
        setattr(fb, field_name, kept)

    candidates = []
    for q in out.questions:
        reason = rule_check_question(q) or (", ".join(check(q)) or None)
        if reason:
            problems.append(f"질문 '{q[:20]}…': {reason}")
        else:
            candidates.append(q)
    open_qs = await _check_questions(ctx, candidates, fb.warnings)
    if len(open_qs) < len(candidates):
        problems.append("답을 유도하는 질문이 있음")
    fb.questions = open_qs[:3]
    if len(fb.questions) < 2:
        problems.append("열린 질문이 2개 미만")

    fb.complete = fb.overall_report is not None and bool(fb.improvements) and len(fb.questions) >= 2
    return problems, fb


async def build_feedback(
    ctx: Ctx, topic: str, req: Requirements, items: list[ItemResult], user_text: str, ai_text: str
) -> Feedback:
    check = _Checker(ctx, topic, req, user_text, ai_text)
    msgs: list[Message] = [
        _system(ctx),
        {"role": "user", "content": ctx.prompts.render("summary", topic=topic, item_results=_item_lines(items))},
    ]
    fb: Feedback | None = None
    for attempt in range(ctx.settings.guardrail_max_retry + 1):
        try:
            out = await generate_structured(ctx.llm, msgs, SummaryOutput, temperature=ctx.settings.llm_temperature)
        except LLMError as e:
            logger.warning("종합 피드백 생성 실패: %r", e)
            break
        problems, fb = await _filter_feedback(ctx, out, check)
        if not problems:
            return fb
        msgs = msgs + [{"role": "assistant", "content": out.model_dump_json()}, _retry_note(ctx, problems)]

    if fb is None:
        return Feedback(warnings=["종합 피드백을 생성하지 못했습니다."])
    fb.warnings.append("일부 피드백이 검사 기준을 통과하지 못해 제외했습니다.")
    return fb


# ---------------------------------------------------------------- 조립


def assemble(ctx: Ctx, comp: Comparison, fb: Feedback, extra_ok: bool = True) -> dict:
    complete = not comp.failed and fb.complete and extra_ok and all(it.action_item for it in comp.items)
    return {
        "status": "done" if complete else "partial",
        "items": comp.items,
        "overall_report": fb.overall_report,
        "strengths": fb.strengths,
        "improvements": fb.improvements,
        "questions": fb.questions,
        "failed_items": comp.failed,
        "warnings": comp.warnings + fb.warnings,
        **ctx.meta(),
    }


async def run(ctx: Ctx, req: AnalyzeRequest) -> AnalysisResult:
    comp = await evaluate_items(ctx, req.topic, req.requirements, req.user_draft, req.ai_draft)
    fb = await build_feedback(ctx, req.topic, req.requirements, comp.items, req.user_draft, req.ai_draft)
    return AnalysisResult(**assemble(ctx, comp, fb))
