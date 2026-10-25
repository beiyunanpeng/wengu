"""P1-5 DoD 复验：真实模型过程题初判评测（开发者脚本，不进 CI）。

用法：
  venv/Scripts/python scripts/eval_grading.py --prefer-dotenv
  venv/Scripts/python scripts/eval_grading.py --prefer-dotenv --model doubao-seed-2-1-lite-260915

对 4 道合成过程题各采样 N 次（默认 3，与批改服务一致），走
llm_prompts/grade.md + 真实 provider.grade（不经 gateway 缓存）。
只记录：JSON 合规率 / 延迟 / tokens / 有效结论与期望的匹配率，
绝不打印题目或作答全文。合成文本题只验证链路与提示词稳定性，
不代表真实手写识别率——Phase 0 边界表仍以家长实拍样本为准。

密钥只从 wengu-api/.env 或环境变量读，绝不打印。未配置 model_prices 时
只记 tokens，不臆造费用。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.core.config import get_runtime_config  # noqa: E402
from app.prompts.loader import load_prompts  # noqa: E402
from app.providers.doubao import DoubaoVisionProvider  # noqa: E402
from app.providers.qwen_vl import QwenVLProvider  # noqa: E402
from dotenv import dotenv_values  # noqa: E402  # pydantic-settings 已依赖 python-dotenv

PROMPTS = API_DIR.parent / "llm_prompts"
PASS_MATCHES = 3

# 合成题：只用于链路/提示词复验，不含真实学生数据。
QUESTIONS = [
    {
        "label": "linear_equation_correct",
        "problem_text": "解方程 2x + 1 = 7，并写出过程。",
        "standard_answer": "2x=6，x=3",
        "student_answer": "2x=6\nx=3",
        "expected": "correct",
    },
    {
        "label": "linear_equation_wrong",
        "problem_text": "解方程 3x - 5 = 10，并写出过程。",
        "standard_answer": "3x=15，x=5",
        "student_answer": "3x=15\nx=6",
        "expected": "wrong",
    },
    {
        "label": "fraction_equation_correct",
        "problem_text": "解方程 x/2 + 1 = 3，并写出过程。",
        "standard_answer": "x/2=2，x=4",
        "student_answer": "x/2=2\nx=4",
        "expected": "correct",
    },
    {
        "label": "two_variable_incomplete",
        "problem_text": "解方程组 x+y=5，x-y=1，写出 x 和 y 的值。",
        "standard_answer": "x=3，y=2",
        "student_answer": "x=3",
        "expected": "uncertain",
    },
]


@dataclass
class QuestionResult:
    label: str
    expected: str
    verdicts: list[str] = field(default_factory=list)
    confidences: list[float | None] = field(default_factory=list)
    latencies: list[int] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    json_failures: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def effective(self) -> str:
        if not self.verdicts:
            return "error"
        return self.verdicts[0] if len(set(self.verdicts)) == 1 else "uncertain"

    @property
    def matched(self) -> bool:
        return self.effective == self.expected


def _pick(dotenv: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = dotenv.get(name) or os.environ.get(name)
        if value:
            return value
    return None


def _build_provider(provider: str, model: str | None, *, prefer_dotenv: bool):
    dotenv = {k: v for k, v in dotenv_values(API_DIR / ".env").items() if v} if prefer_dotenv else {}
    if provider == "doubao":
        api_key = _pick(dotenv, "WENGU_DOUBAO_API_KEY", "ARK_API_KEY")
        base_url = _pick(dotenv, "WENGU_DOUBAO_BASE_URL", "ARK_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3"
        chosen = model or _pick(dotenv, "WENGU_DOUBAO_MODEL_VALUE") or "doubao-seed-2-1-lite-260915"
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


async def _run_question(provider, prompt, question: dict, samples: int) -> QuestionResult:
    result = QuestionResult(label=question["label"], expected=question["expected"])
    rendered = prompt.render(
        PROBLEM_TEXT=question["problem_text"],
        STANDARD_ANSWER=question["standard_answer"],
        STUDENT_ANSWER=question["student_answer"],
    )
    for _ in range(samples):
        try:
            grade, meta = await provider.grade(question["problem_text"], question["student_answer"], prompt=rendered)
        except Exception as exc:
            result.json_failures += 1
            result.errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
            continue
        result.verdicts.append(grade.verdict)
        result.confidences.append(grade.confidence)
        result.latencies.append(meta.latency_ms)
        result.input_tokens += meta.usage.input_tokens
        result.output_tokens += meta.usage.output_tokens
    return result


def _cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = get_runtime_config().model_prices.get(model)
    if not prices:
        return None
    return input_tokens / 1_000_000 * prices.get("input", 0.0) + output_tokens / 1_000_000 * prices.get("output", 0.0)


def _format(result: QuestionResult) -> str:
    if not result.verdicts:
        return f"{result.label:28s} ERROR json_fail={result.json_failures} {result.errors[:1]}"
    p50 = int(statistics.median(result.latencies))
    return (
        f"{result.label:28s} expected={result.expected:9s} effective={result.effective:9s}"
        f" {'PASS' if result.matched else 'FAIL'}"
        f" samples={result.verdicts} p50={p50}ms"
        f" tokens in={result.input_tokens} out={result.output_tokens}"
        f" json_fail={result.json_failures}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="doubao", choices=["doubao", "qwen_vl"])
    parser.add_argument("--model", default=None, help="覆盖默认模型名")
    parser.add_argument("--samples", type=int, default=3, help="每题采样次数（1–3，与批改服务一致）")
    parser.add_argument("--prefer-dotenv", action="store_true", help="wengu-api/.env 优先于进程环境变量")
    args = parser.parse_args()
    if not 1 <= args.samples <= 3:
        raise SystemExit("--samples 必须在 1–3 之间")

    prompt = load_prompts(PROMPTS)["grade"]
    provider = _build_provider(args.provider, args.model, prefer_dotenv=args.prefer_dotenv)
    print(
        f"provider={provider.name} model={provider.model} "
        f"prompt={prompt.id}@{prompt.version} samples={args.samples}"
    )

    results = []
    for question in QUESTIONS:
        result = await _run_question(provider, prompt, question, args.samples)
        results.append(result)
        print(_format(result))

    parsed = [r for r in results if r.verdicts]
    total_samples = sum(len(r.verdicts) + r.json_failures for r in results)
    json_ok = sum(len(r.verdicts) for r in results)
    matches = sum(1 for r in parsed if r.matched)
    latencies = [value for r in parsed for value in r.latencies]
    total_in = sum(r.input_tokens for r in parsed)
    total_out = sum(r.output_tokens for r in parsed)
    cost = _cost(provider.model, total_in, total_out)

    print()
    print(f"JSON 合规   {json_ok}/{total_samples}")
    print(f"有效结论    {matches}/{len(results)} 匹配期望（阈值 {PASS_MATCHES}/{len(results)}）")
    print(
        f"延迟 p50    {int(statistics.median(latencies)) if latencies else 0}ms"
        f" | tokens in={total_in} out={total_out}"
    )
    if cost is None:
        print("费用        model_prices 未配置（config/app-config.json），仅记 tokens")
    else:
        print(f"费用        约 ¥{cost:.4f}（按 model_prices 估算）")
    print("注：合成文本题只验证链路与提示词稳定性，不代表真实手写识别率。")

    ok = json_ok == total_samples and matches >= PASS_MATCHES
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
