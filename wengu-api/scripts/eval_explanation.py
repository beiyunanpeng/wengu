"""P1-8 DoD 复验：真实模型三段式讲解评测（开发者脚本，不进 CI）。

用法：
  venv/Scripts/python scripts/eval_explanation.py --prefer-dotenv
  venv/Scripts/python scripts/eval_explanation.py --prefer-dotenv --provider qwen_vl

对 4 道合成案例分别跑：
- 引导模式 hint=1 与 hint=3（检查结构完整、不泄漏最终答案、质量闸门可通过）
- 完整讲解模式（检查 ≥2 步、答案非空、答案命中期望值）

只记录：结构合规率 / 引导泄漏率 / 完整讲解步数与答案命中 / 延迟 / tokens / 费用，
绝不打印题目、作答或讲解全文。用例是合成文本，不代表真实手写识别率。

密钥只从 wengu-api/.env 或环境变量读，绝不打印。未配置 model_prices 时只记 tokens。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.core.config import get_runtime_config  # noqa: E402
from app.prompts.loader import load_prompts  # noqa: E402
from app.providers.doubao import DoubaoVisionProvider  # noqa: E402
from app.providers.qwen_vl import QwenVLProvider  # noqa: E402
from app.services.explanation import (  # noqa: E402
    LEAK_ANSWER_FIELD_DROPPED,
    LEAK_ANSWER_PHRASE_MASKED,
    LEAK_STANDARD_ANSWER_MASKED,
    MODE_FULL,
    MODE_GUIDE,
    ExplainContext,
    ExplanationQualityError,
    choose_strategy,
    prompt_values,
    quality_gate,
)
from dotenv import dotenv_values  # noqa: E402

PROMPTS_DIR = API_DIR.parent / "llm_prompts"
CASES_PATH = API_DIR / "tests" / "fixtures" / "explanation" / "cases.json"
GUIDE_LEVELS = (1, 3)
LEAK_FLAGS = frozenset(
    {
        LEAK_ANSWER_FIELD_DROPPED,
        LEAK_STANDARD_ANSWER_MASKED,
        LEAK_ANSWER_PHRASE_MASKED,
    }
)
PASS_FULL_MATCHES = 3


def _pick(dotenv: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = dotenv.get(name) or os.environ.get(name)
        if value:
            return value
    return None


def _build_provider(provider: str, model: str | None, *, prefer_dotenv: bool):
    dotenv = (
        {k: v for k, v in dotenv_values(API_DIR / ".env").items() if v}
        if prefer_dotenv
        else {}
    )
    if provider == "doubao":
        api_key = _pick(dotenv, "WENGU_DOUBAO_API_KEY", "ARK_API_KEY")
        base_url = (
            _pick(dotenv, "WENGU_DOUBAO_BASE_URL", "ARK_BASE_URL")
            or "https://ark.cn-beijing.volces.com/api/v3"
        )
        chosen = (
            model
            or _pick(dotenv, "WENGU_DOUBAO_MODEL_VALUE")
            or "doubao-seed-2-1-lite-260915"
        )
        if not api_key:
            raise SystemExit("缺少 WENGU_DOUBAO_API_KEY / ARK_API_KEY")
        return DoubaoVisionProvider(api_key=api_key, model=chosen, base_url=base_url)
    if provider == "qwen_vl":
        api_key = _pick(dotenv, "WENGU_QWEN_API_KEY", "DASHSCOPE_API_KEY")
        base_url = (
            _pick(dotenv, "WENGU_QWEN_BASE_URL", "DASHSCOPE_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        chosen = model or _pick(dotenv, "WENGU_QWEN_MODEL_VALUE") or "qwen-vl-max"
        if not api_key:
            raise SystemExit("缺少 WENGU_QWEN_API_KEY / DASHSCOPE_API_KEY")
        return QwenVLProvider(api_key=api_key, model=chosen, base_url=base_url)
    raise SystemExit(f"未知 provider: {provider}（可选 doubao / qwen_vl）")


def _canon(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        char
        for char in text
        if not char.isspace() and char not in "，。；：、,.;:!?！？（）()【】[]\"'“”‘’"
    )


def _context(case: dict) -> ExplainContext:
    return ExplainContext(
        kind="mistake",
        context_id=0,
        entry=case.get("entry", "mistake"),
        problem_text=case["problem_text"],
        student_answer=case.get("student_answer", ""),
        standard_answer=case.get("standard_answer", ""),
        subject=case.get("subject", ""),
        category_name=case.get("category", ""),
        concepts=tuple(case.get("concepts", ())),
        error_cause=case.get("error_cause"),
    )


@dataclass
class CaseResult:
    label: str
    mode: str
    hint_level: int
    structured: bool = False
    gate_ok: bool = False
    gate_reasons: tuple[str, ...] = ()
    leak_flags: tuple[str, ...] = ()
    step_count: int = 0
    answer_matched: bool | None = None
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""

    @property
    def leak_free(self) -> bool:
        return self.mode == MODE_GUIDE and self.gate_ok and not self.leak_flags


async def _run(
    provider,
    prompts: dict,
    case: dict,
    *,
    mode: str,
    hint_level: int,
) -> CaseResult:
    result = CaseResult(label=case["id"], mode=mode, hint_level=hint_level)
    context = _context(case)
    strategy = choose_strategy(context)
    values = prompt_values(
        context,
        mode=mode,
        strategy=strategy,
        hint_level=hint_level,
        attempted=False,
    )
    prompt = prompts["explain_guide" if mode == MODE_GUIDE else "explain_full"]
    rendered = prompt.render(**values)

    try:
        explanation, meta = await provider.solve_explain(
            context.problem_text, prompt=rendered, hint_level=hint_level
        )
    except Exception as exc:
        result.error = type(exc).__name__
        status = getattr(exc, "status", None)
        if status is not None:
            result.error += f"(status={status})"
        return result

    result.latency_ms = meta.latency_ms
    result.input_tokens = meta.usage.input_tokens
    result.output_tokens = meta.usage.output_tokens
    result.step_count = len(explanation.steps)
    result.structured = bool(
        explanation.focus.strip()
        and explanation.steps
        and explanation.consolidation.strip()
        and (mode == MODE_GUIDE or (explanation.answer or "").strip())
    )

    try:
        gated = quality_gate(
            explanation, mode=mode, standard_answer=context.standard_answer
        )
    except ExplanationQualityError as exc:
        result.gate_reasons = exc.reasons
        return result

    result.gate_ok = True
    result.leak_flags = gated.leak_flags
    if mode == MODE_FULL:
        result.answer_matched = _canon(case["expected_answer"]) in _canon(
            gated.answer or ""
        )
    return result


def _format(result: CaseResult) -> str:
    if result.error:
        return (
            f"{result.label:24s} {result.mode:5s}@{result.hint_level} "
            f"ERROR {result.error}"
        )
    if result.mode == MODE_GUIDE:
        return (
            f"{result.label:24s} guide@{result.hint_level} "
            f"struct={'OK' if result.structured else 'FAIL'} "
            f"leak_free={'OK' if result.leak_free else 'FAIL'} "
            f"gate={'OK' if result.gate_ok else ','.join(result.gate_reasons)} "
            f"steps={result.step_count} p50={result.latency_ms}ms "
            f"tokens in={result.input_tokens} out={result.output_tokens}"
        )
    return (
        f"{result.label:24s} full    "
        f"struct={'OK' if result.structured else 'FAIL'} "
        f"steps={result.step_count} "
        f"answer_match={'PASS' if result.answer_matched else 'FAIL'} "
        f"gate={'OK' if result.gate_ok else ','.join(result.gate_reasons)} "
        f"p50={result.latency_ms}ms "
        f"tokens in={result.input_tokens} out={result.output_tokens}"
    )


def _cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = get_runtime_config().model_prices.get(model)
    if not prices:
        return None
    return input_tokens / 1_000_000 * prices.get("input", 0.0) + output_tokens / 1_000_000 * prices.get("output", 0.0)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="doubao", choices=["doubao", "qwen_vl"])
    parser.add_argument("--model", default=None, help="覆盖默认模型名")
    parser.add_argument(
        "--prefer-dotenv", action="store_true", help="wengu-api/.env 优先于进程环境变量"
    )
    args = parser.parse_args()

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    prompts = load_prompts(PROMPTS_DIR)
    provider = _build_provider(args.provider, args.model, prefer_dotenv=args.prefer_dotenv)
    print(
        f"provider={provider.name} model={provider.model} "
        f"guide={prompts['explain_guide'].id}@{prompts['explain_guide'].version} "
        f"full={prompts['explain_full'].id}@{prompts['explain_full'].version} "
        f"cases={len(cases)}"
    )

    results: list[CaseResult] = []
    for case in cases:
        for level in GUIDE_LEVELS:
            result = await _run(
                provider, prompts, case, mode=MODE_GUIDE, hint_level=level
            )
            results.append(result)
            print(_format(result))
        full = await _run(provider, prompts, case, mode=MODE_FULL, hint_level=0)
        results.append(full)
        print(_format(full))

    guide = [row for row in results if row.mode == MODE_GUIDE]
    full_rows = [row for row in results if row.mode == MODE_FULL]
    latencies = [row.latency_ms for row in results if not row.error and row.latency_ms]
    total_in = sum(row.input_tokens for row in results)
    total_out = sum(row.output_tokens for row in results)
    cost = _cost(provider.model, total_in, total_out)

    print()
    print(f"结构合规    {sum(1 for row in results if row.structured)}/{len(results)}")
    print(
        f"引导零泄漏  {sum(1 for row in guide if row.leak_free)}/{len(guide)}"
        f"（闸门拦截 {sum(1 for row in guide if row.leak_flags)} 次）"
    )
    print(
        f"完整讲解    ≥2步 {sum(1 for row in full_rows if row.gate_ok and row.step_count >= 2)}/{len(full_rows)}"
        f" | 答案命中 {sum(1 for row in full_rows if row.answer_matched)}/{len(full_rows)}"
        f"（阈值 {PASS_FULL_MATCHES}/{len(full_rows)}）"
    )
    print(
        f"延迟 p50    {int(statistics.median(latencies)) if latencies else 0}ms"
        f" | tokens in={total_in} out={total_out}"
    )
    if cost is None:
        print("费用        model_prices 未配置（config/app-config.json），仅记 tokens")
    else:
        print(f"费用        约 ¥{cost:.4f}（按 model_prices 估算）")
    print("注：合成文本用例只验证链路/提示词稳定性，不代表真实手写学情。")

    ok = (
        all(row.structured for row in results)
        and all(row.leak_free for row in guide)
        and all(row.gate_ok and row.step_count >= 2 for row in full_rows)
        and sum(1 for row in full_rows if row.answer_matched) >= PASS_FULL_MATCHES
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
