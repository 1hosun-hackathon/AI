"""analyze v2

1. 항목 채점: 글마다 따로(항목 5 × 글 2). 두 글을 나란히 놓으면 매끄러운 쪽으로 점수가 쏠리기 때문이다.
2. 비교 설명 1회: 점수는 고정된 상태에서 항목별 차이만 설명한다.
3. 종합 피드백 1회 → 규칙 검사(대필·질문 형식) → 피드백 판정 1회(입장 변경 권유, 유도 질문)
4. 조립
"""

import asyncio
import logging
from dataclasses import dataclass, field

from app.errors import AppError
from app.guardrails.citation import resolve_evidence
from app.guardrails.ghostwriting import ghostwriting_issues
from app.guardrails.questions import rule_check_question
from app.llm.base import LLMError, Message
from app.llm.outputs import (
    CompareOutput,
    FeedbackCheckOutput,
    SummaryOutput,
    TextScoreOutput,
    TextScoreWithActionOutput,
)
from app.llm.structured import generate_structured
from app.pipelines.context import Ctx
from app.schemas.analysis import AnalysisResult, AnalyzeRequest, Evidence, ItemResult
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


# ---------------------------------------------------------------- 1. 항목 채점


async def _score_text(
    ctx: Ctx, topic: str, key: str, sentences: list[str], *, with_action: bool, check: _Checker
) -> tuple[TextScoreOutput, list[str]]:
    """글 한 편을 항목 하나로 채점. with_action이면 보완 방향도 받고 대필 검사 후 재생성한다."""
    s = ctx.settings
    name, desc = CRITERIA_INFO[key]
    msgs: list[Message] = [
        _system(ctx),
        {
            "role": "user",
            "content": ctx.prompts.render(
                "item_score",
                topic=topic,
                name=name,
                description=desc,
                rubric=ctx.prompts.rubric(key),
                text=numbered(sentences),
                action_task=ctx.prompts.raw("action_task") if with_action else "",
            ),
        },
    ]
    model = TextScoreWithActionOutput if with_action else TextScoreOutput
    out = await generate_structured(ctx.llm, msgs, model, temperature=s.llm_temperature)
    if not with_action:
        return out, []
    issues = check(out.action)
    for _ in range(s.guardrail_max_retry):
        if not issues:
            break
        retry = msgs + [{"role": "assistant", "content": out.model_dump_json()}, _retry_note(ctx, issues)]
        out = await generate_structured(ctx.llm, retry, model, temperature=s.llm_temperature)
        issues = check(out.action)
    return out, issues


@dataclass
class _Scored:
    key: str
    user: TextScoreWithActionOutput
    user_issues: list[str]
    ai_score: int
    ai_summary: str
    ai_evidence: list[Evidence]


async def _compare(ctx: Ctx, topic: str, user_s: list[str], ai_s: list[str], scored: list[_Scored]) -> dict[str, str]:
    """항목별 비교 설명. A/B 배정은 무작위로 하고 결과의 라벨은 사용자용 이름으로 바꾼다."""
    user_is_a = ctx.rng.random() < 0.5
    names = {"A": USER_NAME, "B": AI_NAME} if user_is_a else {"A": AI_NAME, "B": USER_NAME}
    lines = []
    for x in scored:
        u = (x.user.score, x.user.summary)
        a = (x.ai_score, x.ai_summary)
        first, second = (u, a) if user_is_a else (a, u)
        lines.append(
            f"- {x.key} ({CRITERIA_INFO[x.key][0]}): A {first[0]}점 - {first[1]} / B {second[0]}점 - {second[1]}"
        )
    msgs: list[Message] = [
        _system(ctx),
        {
            "role": "user",
            "content": ctx.prompts.render(
                "compare",
                topic=topic,
                text_a=numbered(user_s if user_is_a else ai_s),
                text_b=numbered(ai_s if user_is_a else user_s),
                item_results="\n".join(lines),
            ),
        },
    ]
    try:
        out = await generate_structured(ctx.llm, msgs, CompareOutput, temperature=ctx.settings.llm_temperature)
    except LLMError as e:
        logger.warning("비교 설명 생성 실패: %r", e)
        return {}
    return {c.key: relabel(c.comparison, names) for c in out.comparisons}


async def evaluate_items(
    ctx: Ctx,
    topic: str,
    req: Requirements,
    user_text: str,
    ai_text: str,
    *,
    fixed_ai: dict[str, ItemResult] | None = None,
) -> Comparison:
    """fixed_ai가 주어지면 그 항목의 AI 글 점수·요약·근거를 다시 매기지 않고 그대로 쓴다(재분석)."""
    fixed_ai = fixed_ai or {}
    user_s, ai_s = split_sentences(user_text), split_sentences(ai_text)
    check = _Checker(ctx, topic, req, user_text, ai_text)

    ai_keys = [k for k in CRITERIA if k not in fixed_ai]
    results = await asyncio.gather(
        *(_score_text(ctx, topic, k, user_s, with_action=True, check=check) for k in CRITERIA),
        *(_score_text(ctx, topic, k, ai_s, with_action=False, check=check) for k in ai_keys),
        return_exceptions=True,
    )
    user_res = dict(zip(CRITERIA, results[: len(CRITERIA)]))
    ai_res = dict(zip(ai_keys, results[len(CRITERIA) :]))

    scored: list[_Scored] = []
    failed: list[str] = []
    errors: list[BaseException] = []
    warnings: list[str] = []
    for key in CRITERIA:
        u = user_res[key]
        a = fixed_ai.get(key) or ai_res[key]
        bad = [r for r in (u, a) if isinstance(r, BaseException)]
        if bad:
            logger.warning("항목 %s 채점 실패: %r", key, bad[0])
            failed.append(key)
            errors.append(bad[0])
            continue
        user_out, issues = u
        if isinstance(a, ItemResult):
            ai_score, ai_summary = a.ai_score, a.ai_summary
            ai_evidence = [e for e in a.evidence if e.source == "ai"]
        else:
            ai_out, _ = a
            ai_score, ai_summary = ai_out.score, ai_out.summary
            ai_evidence = resolve_evidence(ai_out.evidence, ai_s, "ai")
        if issues:
            warnings.append(f"{CRITERIA_INFO[key][0]}: 보완 방향 제외 ({', '.join(issues)})")
        scored.append(_Scored(key, user_out, issues, ai_score, ai_summary, ai_evidence))

    if not scored:
        first = errors[0]
        if isinstance(first, (AppError, LLMError)):
            raise first
        raise AppError("INTERNAL", detail=repr(first))

    comparisons = await _compare(ctx, topic, user_s, ai_s, scored)
    if len(comparisons) < len(scored):
        warnings.append("일부 항목의 비교 설명을 생성하지 못해 점수 요약으로 대신했습니다.")

    items = []
    for x in scored:
        u_score = x.user.score
        better = "user" if u_score > x.ai_score else "ai" if u_score < x.ai_score else "tie"
        items.append(
            ItemResult(
                key=x.key,
                user_score=u_score,
                ai_score=x.ai_score,
                user_summary=x.user.summary,
                ai_summary=x.ai_summary,
                comparison=comparisons.get(x.key)
                or f"이 항목에서 {USER_NAME}은 {u_score}점, {AI_NAME}은 {x.ai_score}점이에요.",
                evidence=resolve_evidence(x.user.evidence, user_s, "user") + x.ai_evidence,
                better=better,
                action_item=None if x.user_issues else x.user.action,
            )
        )
    return Comparison(items=items, failed=failed, warnings=warnings)


# ---------------------------------------------------------------- 3. 종합 피드백


def _item_lines(items: list[ItemResult]) -> str:
    lines = []
    for it in items:
        name = CRITERIA_INFO[it.key][0]
        lines.append(
            f"- {name}: 학습자 {it.user_score}점 / AI {it.ai_score}점\n"
            f"  학습자 글: {it.user_summary}\n  AI 글: {it.ai_summary}\n  비교: {it.comparison}"
        )
    return "\n".join(lines)


def _theses(items: list[ItemResult]) -> tuple[str, str]:
    thesis = next((it for it in items if it.key == "thesis"), None)
    if thesis is None:
        return "(알 수 없음)", "(알 수 없음)"
    return thesis.user_summary, thesis.ai_summary


async def _judge(
    ctx: Ctx, topic: str, theses: tuple[str, str], entries: list[tuple[str, str]], warnings: list[str]
) -> list[str]:
    """피드백 문장 판정: ok | stance_shift | leading. 실패하면 모두 ok로 보고 경고만 남긴다."""
    if not entries:
        return []
    kinds = {"action": "보완 방향", "improvement": "보완할 점", "question": "질문"}
    listing = "\n".join(f"{i}. ({kinds[k]}) {t}" for i, (k, t) in enumerate(entries))
    msgs: list[Message] = [
        _system(ctx),
        {
            "role": "user",
            "content": ctx.prompts.render(
                "feedback_check", topic=topic, user_thesis=theses[0], ai_thesis=theses[1], entries=listing
            ),
        },
    ]
    try:
        out = await generate_structured(ctx.llm, msgs, FeedbackCheckOutput, temperature=0.0)
    except LLMError as e:
        logger.warning("피드백 판정 실패: %r", e)
        warnings.append("피드백 판정(입장 변경·유도 질문)을 건너뛰었습니다.")
        return ["ok"] * len(entries)
    verdicts = {v.index: v.verdict for v in out.verdicts}
    return [verdicts.get(i, "ok") for i in range(len(entries))]


_REASON = {"stance_shift": "입장을 바꾸거나 절충하라고 권함", "leading": "답을 유도하는 질문"}


async def _filter_feedback(
    ctx: Ctx,
    topic: str,
    out: SummaryOutput,
    check: _Checker,
    items: list[ItemResult],
    *,
    judge_actions: bool,
) -> tuple[list[str], Feedback]:
    problems: list[str] = []
    fb = Feedback()

    report_issues = check(out.overall_report)
    if report_issues:
        problems.append(f"종합 리포트: {', '.join(report_issues)}")
    else:
        fb.overall_report = out.overall_report

    for text in out.strengths:
        issues = check(text)
        if issues:
            problems.append(f"강점 '{text[:20]}…': {', '.join(issues)}")
        else:
            fb.strengths.append(text)

    improvements = []
    for text in out.improvements:
        issues = check(text)
        if issues:
            problems.append(f"보완할 점 '{text[:20]}…': {', '.join(issues)}")
        else:
            improvements.append(text)

    questions = []
    for q in out.questions:
        reason = rule_check_question(q) or (", ".join(check(q)) or None)
        if reason:
            problems.append(f"질문 '{q[:20]}…': {reason}")
        else:
            questions.append(q)

    # 규칙 검사를 통과한 것만 LLM으로 판정한다 (호출 1회).
    actions = [it for it in items if it.action_item] if judge_actions else []
    entries = (
        [("action", it.action_item) for it in actions]
        + [("improvement", t) for t in improvements]
        + [("question", q) for q in questions]
    )
    verdicts = await _judge(ctx, topic, _theses(items), entries, fb.warnings)
    v_actions = verdicts[: len(actions)]
    v_improvements = verdicts[len(actions) : len(actions) + len(improvements)]
    v_questions = verdicts[len(actions) + len(improvements) :]

    for it, v in zip(actions, v_actions):
        if v == "stance_shift":
            fb.warnings.append(f"{CRITERIA_INFO[it.key][0]}: 보완 방향 제외 ({_REASON[v]})")
            it.action_item = None
    for text, v in zip(improvements, v_improvements):
        if v == "stance_shift":
            problems.append(f"보완할 점 '{text[:20]}…': {_REASON[v]}")
        else:
            fb.improvements.append(text)
    open_qs = []
    for q, v in zip(questions, v_questions):
        if v in _REASON:
            problems.append(f"질문 '{q[:20]}…': {_REASON[v]}")
        else:
            open_qs.append(q)
    fb.questions = open_qs[:3]
    if len(fb.questions) < 2:
        problems.append("열린 질문이 2개 미만")

    fb.complete = fb.overall_report is not None and bool(fb.improvements) and len(fb.questions) >= 2
    return problems, fb


async def build_feedback(
    ctx: Ctx, topic: str, req: Requirements, items: list[ItemResult], user_text: str, ai_text: str
) -> Feedback:
    """종합 피드백 생성 + 검사. 문제가 있으면 사유를 알려주고 재생성한다. items의 action_item을 걸러낼 수 있다."""
    check = _Checker(ctx, topic, req, user_text, ai_text)
    user_thesis, ai_thesis = _theses(items)
    msgs: list[Message] = [
        _system(ctx),
        {
            "role": "user",
            "content": ctx.prompts.render(
                "summary",
                topic=topic,
                user_thesis=user_thesis,
                ai_thesis=ai_thesis,
                item_results=_item_lines(items),
            ),
        },
    ]
    fb: Feedback | None = None
    action_warnings: list[str] = []
    problems: list[str] = []
    question_pool: list[str] = []  # 시도마다 통과한 질문을 모은다
    for attempt in range(ctx.settings.guardrail_max_retry + 1):
        try:
            out = await generate_structured(ctx.llm, msgs, SummaryOutput, temperature=ctx.settings.llm_temperature)
        except LLMError as e:
            logger.warning("종합 피드백 생성 실패: %r", e)
            break
        problems, fb = await _filter_feedback(ctx, topic, out, check, items, judge_actions=attempt == 0)
        if attempt == 0:
            action_warnings = [w for w in fb.warnings if "보완 방향 제외" in w]
        question_pool += [q for q in fb.questions if q not in question_pool]
        enough_questions = len(question_pool) >= 2
        if enough_questions:
            problems = [p for p in problems if p != "열린 질문이 2개 미만"]
        # 질문은 이미 충분하면 일부가 걸러졌다는 이유만으로 재생성하지 않는다.
        blocking = [p for p in problems if not (enough_questions and p.startswith("질문 "))]
        if not blocking:
            break
        msgs = msgs + [{"role": "assistant", "content": out.model_dump_json()}, _retry_note(ctx, blocking)]

    if fb is None:
        return Feedback(warnings=action_warnings + ["종합 피드백을 생성하지 못했습니다."])
    fb.questions = question_pool[:3]
    fb.complete = fb.overall_report is not None and bool(fb.improvements) and len(fb.questions) >= 2
    fb.warnings = action_warnings + [w for w in fb.warnings if w not in action_warnings]
    fb.warnings += [f"제외: {p}" for p in problems]
    return fb


# ---------------------------------------------------------------- 4. 조립


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
