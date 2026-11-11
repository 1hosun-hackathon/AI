"""평가 샘플로 analyze 파이프라인을 실제 Ollama에서 돌려 기대 결과와 비교한다.

사용법:
    python scripts/eval_models.py gemma4:e2b-it-qat --samples tests/fixtures/report_samples.json --out outputs/eval.json
    python scripts/eval_models.py gemma4:e2b-it-qat qwen3:4b --runs 1
    python scripts/eval_models.py gemma4:e2b-it-qat --ids smartphone_strong failure_weak

- 리포트 샘플(report_samples.json)은 추가로 중립성(결론만 다른 두 글의 점수 차),
  구조 민감도(같은 문장을 뒤섞은 글과의 구성·논리 점수 차), 수준 구분을 검사한다.

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
    variant_checks(samples, ok)
    return records


def _mean(scores: dict[str, int], keys=None) -> float:
    vals = [v for k, v in scores.items() if keys is None or k in keys]
    return statistics.mean(vals) if vals else float("nan")


def variant_checks(samples: list[dict], records: list[dict]) -> None:
    """리포트 샘플(variant 필드)용 검사: 중립성, 구조 민감도, 수준 구분."""
    by_id = {s["id"]: s for s in samples}
    groups: dict[str, dict[str, dict[str, int]]] = {}
    for r in records:
        s = by_id[r["id"]]
        if "variant" not in s:
            return
        scores = {it["key"]: it["user_score"] for it in r["result"]["items"]}
        groups.setdefault(s["topic_id"], {})[s["variant"]] = scores
    struct_logic = ("structure", "originality")  # 구성 + 논리 전개
    print("\n주제                 약한 글  강한 A  강한 B  뒤섞음 | 중립성 |A-B|<=0.4 | 구조 민감도 A-뒤섞음>=1.0 | 수준 강한-약한>=1.0")
    passed = {"neutral": 0, "structure": 0, "level": 0}
    for topic_id, v in groups.items():
        if not {"weak", "strong_a", "strong_b", "scrambled"} <= v.keys():
            continue
        w, a, b, sc = (_mean(v[k]) for k in ("weak", "strong_a", "strong_b", "scrambled"))
        # 평균 점수의 부동소수점 오차(0.4000000001 > 0.4)로 판정이 뒤집히지 않도록 반올림
        neutral = round(abs(a - b), 6)
        struct = round(_mean(v["strong_a"], struct_logic) - _mean(v["scrambled"], struct_logic), 6)
        level = round(min(a, b) - w, 6)
        ok_n, ok_s, ok_l = neutral <= 0.4, struct >= 1.0, level >= 1.0
        passed["neutral"] += ok_n
        passed["structure"] += ok_s
        passed["level"] += ok_l
        print(
            f"{topic_id:18s} {w:6.1f} {a:7.1f} {b:7.1f} {sc:7.1f} | "
            f"{neutral:4.1f} {'OK' if ok_n else 'XX'}          | {struct:+4.1f} {'OK' if ok_s else 'XX'}                | "
            f"{level:+4.1f} {'OK' if ok_l else 'XX'}"
        )
    n = len(groups)
    print(f"--- 중립성 {passed['neutral']}/{n} | 구조 민감도 {passed['structure']}/{n} | 수준 구분 {passed['level']}/{n}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--ids", nargs="*", help="이 id의 샘플만 실행")
    ap.add_argument("--out", type=Path, help="전체 결과 JSON 저장 경로")
    ap.add_argument("--samples", type=Path, default=SAMPLES, help="샘플 파일 (기본: 논설문·에세이 samples.json)")
    args = ap.parse_args()
    samples = json.loads(args.samples.read_text(encoding="utf-8"))
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
