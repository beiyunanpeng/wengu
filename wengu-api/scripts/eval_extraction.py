"""P1-4 DoD 复验：真实 VLM 结构化提取 + 质量闸门评测（开发者脚本，不进 CI）。

用法：
  venv/Scripts/python scripts/eval_extraction.py --prefer-dotenv
  venv/Scripts/python scripts/eval_extraction.py --prefer-dotenv --provider qwen_vl
  venv/Scripts/python scripts/eval_extraction.py --only q04,q08 --verbose

对 tests/fixtures/extraction 下每张单题图调用真实 provider.extract_problem
（prompt 唯一真源 llm_prompts/extract_problem.md），再走 apply_extraction_gate，
与 truth.json 比对：JSON 解析率 / 题目与作答相似度 / 闸门命中 / 延迟 / tokens。
非探索题任一失败则退出码 1；探索题只报告不阻断。

密钥只从 wengu-api/.env 或环境变量读，绝不打印；不落库、不经 gateway，
输出不含题目全文（--verbose 仅打印失败项首 40 字）。合成 fixture 只验证
链路与闸门，不代表真实手写识别率——Phase 0 边界表仍以家长实拍样本为准。
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.prompts.loader import load_prompts  # noqa: E402
from app.providers.doubao import DoubaoVisionProvider  # noqa: E402
from app.providers.qwen_vl import QwenVLProvider  # noqa: E402
from app.services.extraction import (  # noqa: E402
    SOURCE_SLICE,
    apply_extraction_gate,
)
from dotenv import dotenv_values  # noqa: E402  # pydantic-settings 已依赖 python-dotenv

FIXTURES = API_DIR / "tests" / "fixtures" / "extraction"
PROMPTS = API_DIR.parent / "llm_prompts"
SIMILARITY_THRESHOLD = 0.85


@dataclass
class ItemResult:
    file: str
    label: str
    exploratory: bool
    gate: str = ""
    expected_gate: str = ""
    reasons: tuple[str, ...] = ()
    expected_reasons: tuple[str, ...] = ()
    problem_sim: float = 0.0
    answer_sim: float = 0.0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    forbidden_hit: bool = False
    error: str | None = None
    actual_problem_head: str = ""
    actual_answer: str | None = None

    @property
    def gate_ok(self) -> bool:
        return self.gate == self.expected_gate

    @property
    def reasons_ok(self) -> bool:
        return set(self.expected_reasons) <= set(self.reasons)

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.problem_sim >= SIMILARITY_THRESHOLD
            and self.answer_sim >= SIMILARITY_THRESHOLD
            and self.gate_ok
            and self.reasons_ok
            and not self.forbidden_hit
        )


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _problem_similarity(truth: dict, actual: str) -> float:
    expected = str(truth.get("problem_text") or "")
    if truth.get("problem_text_scope") == "contains":
        return 1.0 if _normalize(expected) in _normalize(actual) else 0.0
    return _similarity(expected, actual)


def _answer_similarity(expected: str | None, actual: str | None) -> float:
    if expected is None:
        return 1.0 if actual is None else 0.0
    if actual is None:
        return 0.0
    return _similarity(expected, actual)


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


async def _run_item(provider, prompt_text: str, truth: dict, fixtures: Path) -> ItemResult:
    result = ItemResult(
        file=truth["file"],
        label=truth["label"],
        exploratory=bool(truth.get("exploratory")),
        expected_gate=truth["expected_gate"],
        expected_reasons=tuple(truth.get("expected_reasons") or ()),
    )
    image_path = fixtures / truth["file"]
    try:
        if not image_path.is_file():
            raise FileNotFoundError(f"fixture missing: {image_path.name}")
        extracted, meta = await provider.extract_problem(str(image_path), prompt=prompt_text)
        decision = apply_extraction_gate(extracted, source_kind=SOURCE_SLICE)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        return result

    result.gate = decision.gate_status
    result.reasons = decision.review_reasons
    result.problem_sim = _problem_similarity(truth, decision.problem_text)
    result.answer_sim = _answer_similarity(truth.get("student_answer"), decision.student_answer)
    result.latency_ms = meta.latency_ms
    result.input_tokens = meta.usage.input_tokens
    result.output_tokens = meta.usage.output_tokens
    result.actual_problem_head = decision.problem_text[:40]
    result.actual_answer = decision.student_answer
    forbidden = [str(item) for item in truth.get("forbidden_answers") or ()]
    result.forbidden_hit = bool(
        forbidden
        and decision.student_answer
        and any(_normalize(item) in _normalize(decision.student_answer) for item in forbidden)
    )
    return result


def _format_item(result: ItemResult, *, verbose: bool) -> str:
    if result.error is not None:
        return f"{result.file:24s} ERROR {result.error}"
    mark = "EXPLORATORY" if result.exploratory else ("PASS" if result.passed else "FAIL")
    line = (
        f"{result.file:24s} {mark:12s}"
        f" gate={result.gate}(期望 {result.expected_gate})"
        f" 题目={result.problem_sim:.3f} 作答={result.answer_sim:.3f}"
        f" {result.latency_ms}ms in={result.input_tokens} out={result.output_tokens}"
    )
    if result.reasons and result.reasons != result.expected_reasons:
        line += f" reasons={list(result.reasons)}"
    if result.forbidden_hit:
        line += " [注入命中:作答出现禁用值]"
    if verbose and not result.exploratory and not result.passed:
        line += f"\n    实际题目: {result.actual_problem_head!r} 实际作答: {result.actual_answer!r}"
    return line


def _summary(results: list[ItemResult]) -> tuple[list[str], bool]:
    parsed = [r for r in results if r.error is None]
    required = [r for r in results if not r.exploratory]
    passed_required = [r for r in required if r.passed]
    gate_hits = sum(1 for r in parsed if r.gate_ok)
    latencies = sorted(r.latency_ms for r in parsed)
    p50 = latencies[len(latencies) // 2] if latencies else 0
    avg_problem = sum(r.problem_sim for r in parsed) / max(1, len(parsed))
    avg_answer = sum(r.answer_sim for r in parsed) / max(1, len(parsed))
    total_in = sum(r.input_tokens for r in parsed)
    total_out = sum(r.output_tokens for r in parsed)
    all_pass = len(passed_required) == len(required)

    lines = [
        "",
        f"解析成功   {len(parsed)}/{len(results)}",
        f"题目相似度 {avg_problem:.3f} | 作答相似度 {avg_answer:.3f}（阈值 {SIMILARITY_THRESHOLD:.2f}）",
        f"闸门命中   {gate_hits}/{len(parsed)} | 延迟 p50 {p50}ms | tokens in={total_in} out={total_out}",
        f"非探索题   {len(passed_required)}/{len(required)} 通过 → {'全部通过' if all_pass else '存在失败'}",
        "注：合成印刷体 fixture，非真实手写；Phase 0 边界表仍以实拍样本为准。",
    ]
    return lines, all_pass


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--truth", type=Path, default=None)
    parser.add_argument("--provider", default="doubao", choices=["doubao", "qwen_vl"])
    parser.add_argument("--model", default=None, help="覆盖默认模型名")
    parser.add_argument("--only", default=None, help="只跑文件名匹配这些前缀的题，逗号分隔")
    parser.add_argument("--prefer-dotenv", action="store_true", help="wengu-api/.env 优先于进程环境变量")
    parser.add_argument("--verbose", action="store_true", help="失败项额外打印实际文本首 40 字")
    args = parser.parse_args()

    truth_path = args.truth or (args.fixtures / "truth.json")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    questions = truth["questions"]
    if args.only:
        tokens = [token.strip() for token in args.only.split(",") if token.strip()]
        questions = [q for q in questions if any(token in q["file"] for token in tokens)]
    if not questions:
        raise SystemExit("没有匹配的评测题")

    prompt = load_prompts(PROMPTS)["extract_problem"]
    provider = _build_provider(args.provider, args.model, prefer_dotenv=args.prefer_dotenv)
    print(
        f"provider={provider.name} model={provider.model} "
        f"prompt={prompt.id}@{prompt.version} source_kind={truth.get('source_kind', SOURCE_SLICE)}"
    )

    results = []
    for question in questions:
        result = await _run_item(provider, prompt.template, question, args.fixtures)
        results.append(result)
        print(_format_item(result, verbose=args.verbose))

    summary, all_pass = _summary(results)
    print("\n".join(summary))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
