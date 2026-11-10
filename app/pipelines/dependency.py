"""dependency: LLM 없이 임베딩 유사도로 최종 글의 AI 의존도를 계산한다."""

from dataclasses import asdict

from app.embeddings.similarity import Thresholds, dependency_ratio, label_sentences
from app.pipelines.context import Ctx
from app.schemas.dependency import DependencyMethod, DependencyRequest, DependencyResponse, SentenceLabel

_DESCRIPTION = (
    "완성한 글을 문장 단위로 나눈 뒤, 각 문장이 내 초안과 AI 참고 글 중 어느 쪽과 뜻이 가까운지 비교했어요. "
    "AI 참고 글의 문장과 유사도가 {ai:.2f} 이상이고 내 초안보다 AI 글에 더 가까우면 'AI와 유사', "
    "내 초안과 유사도가 {keep:.2f} 이상이면 '내 초안 유지', 그 외는 '새로 쓴 문장'으로 분류해요. "
    "비율은 문장의 글자 수(공백 제외)로 계산하고, {min}자 미만의 짧은 문장은 비율 계산에서 뺐어요."
)


async def run(ctx: Ctx, req: DependencyRequest) -> DependencyResponse:
    s = ctx.settings
    th = Thresholds(ai_similar=s.ai_similar_threshold, keep=s.keep_threshold, min_sentence_chars=s.min_sentence_chars)
    sentences = await label_sentences(ctx.llm, req.user_draft, req.final_text, req.ai_draft, th)
    ai_ratio = round(dependency_ratio(sentences, th.min_sentence_chars), 4)
    return DependencyResponse(
        self_composition_ratio=round(1 - ai_ratio, 4),
        ai_dependency_ratio=ai_ratio,
        sentences=[SentenceLabel(**asdict(x)) for x in sentences],
        method=DependencyMethod(
            embedding_model=ctx.llm.embed_model_name,
            ai_similar_threshold=th.ai_similar,
            keep_threshold=th.keep,
            description=_DESCRIPTION.format(ai=th.ai_similar, keep=th.keep, min=th.min_sentence_chars),
        ),
        prompt_version=ctx.prompts.version,
        model=ctx.llm.embed_model_name,
    )
