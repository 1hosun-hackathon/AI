"""평가 샘플로 analyze 파이프라인을 실제 Ollama에서 돌려 기대 결과와 비교한다.

사용법:
    python scripts/eval_models.py gemma4:e2b-it-qat qwen3:4b --runs 1 --out outputs/eval.json
    python scripts/eval_models.py gemma4:e2b-it-qat --ids smartphone_strong failure_weak

- 판정: 학습자 평균 점수 - AI 평균 점수 ≥ +0.5 → user, ≤ -0.5 → ai, 그 사이 → similar
- --runs 2 이상이면 seed를 바꿔 같은 글의 점수가 얼마나 흔들리는지 본다.
- 전체 결과(피드백 문장 포함)는 --out 파일에 저장한다. 입장 쏠림 등은 이 파일을 읽어 확인한다.
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from app.config import Settings
from app.llm.ollama import OllamaProvider
from app.pipelines import analyze
from app.pipelines.context import Ctx
from app.prompts.loader import Prompts
from app.schemas.analysis import AnalyzeRequest

SAMPLES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "samples.json"


def verdict(diff: float) -> str:
    return "user" if diff >= 0.5 else "ai" if diff <= -0.5 else "similar"


async def eval_model(model: str, runs: int, samples: list[dict]) -> list[dict]:
    print(f"\n=== {model}")
    print(f"{'샘플':24s} {'기대':8s} {'실제':8s} {'차이':>5s}  학습자/AI 점수 (논지 근거 구조 표현 독창성)   상태     시간")
    records = []
    for sample in samples:
        req = AnalyzeRequest(**{k: sample[k] for k in ("topic", "requirements", "user_draft", "ai_draft")})
        for i in range(runs):
            settings = Settings(_env_file=None, llm_model=model, llm_seed=42 + i, warmup=False)
            llm = OllamaProvider(settings)
            ctx = Ctx(llm=llm, settings=settings, prompts=Prompts(settings.prompt_version))
            t0 = time.time()
            try:
                res = await analyze.run(ctx, req)
            except Exception as e:  # noqa: BLE001
                print(f"{sample['id']:24s} 실패: {e!r}")
                records.append({"id": sample["id"], "run": i, "error": repr(e)})
                continue
            finally:
                await llm.aclose()
            dt = time.time() - t0
            us = [it.user_score for it in res.items]
            ai = [it.ai_score for it in res.items]
            diff = statistics.mean(us) - statistics.mean(ai)
            got = verdict(diff)
            exp = sample.get("expected", {}).get("overall", "-")
            mark = "OK" if got == exp else "XX"
            print(
                f"{sample['id']:24s} {exp:8s} {got:8s} {diff:+5.1f}  {us} / {ai}   "
                f"{res.status:8s} {dt:4.0f}초 {mark}"
            )
            records.append(
                {"id": sample["id"], "run": i, "model": model, "expected": sample.get("expected"),
                 "verdict": got, "diff": diff, "seconds": dt, "result": res.model_dump(mode="json")}
            )
    ok = [r for r in records if "verdict" in r]
    hit = sum(r["verdict"] == (r["expected"] or {}).get("overall") for r in ok)
    print(f"--- 기대 일치 {hit}/{len(ok)} | 평균 {statistics.mean([r['seconds'] for r in ok] or [0]):.0f}초")
    return records


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--ids", nargs="*", help="이 id의 샘플만 실행")
    ap.add_argument("--out", type=Path, help="전체 결과 JSON 저장 경로")
    args = ap.parse_args()
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    if args.ids:
        samples = [s for s in samples if s["id"] in args.ids]
    records = []
    for model in args.models:
        records += await eval_model(model, args.runs, samples)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
