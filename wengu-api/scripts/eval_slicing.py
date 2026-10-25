"""P1-3b DoD 复验：整页直读 vs 切题后逐题识别的 VLM 转写质量对比（开发者脚本）。

对同一张图（默认 tests/fixtures/two_page_spread.png，ground truth 已知）：
  模式 A：整页图直接喂 VLM 转写全部题目
  模式 B：本地 OCR 行聚类切成单题子图，逐题转写
用 difflib 与 ground truth 比对（空白归一化后的相似度），输出两边均分。

用法：
  venv/Scripts/python scripts/eval_slicing.py --prefer-dotenv
  venv/Scripts/python scripts/eval_slicing.py --image 真实照片.jpg --truth 对应truth.json

不进 CI；真实密钥只从 .env / 环境变量读，绝不打印。走 P1-2 http 层直连，
不经 gateway（不触发缓存/护栏），运行信息（provider/model/prompt_version/usage）打印到控制台。
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.preprocess.ocr import get_ocr_engine  # noqa: E402
from app.prompts.loader import load_prompts  # noqa: E402
from app.providers.http import chat_completions, image_to_data_url  # noqa: E402
from app.services.slicer import plan_slices  # noqa: E402
from dotenv import dotenv_values  # noqa: E402  # pydantic-settings 已依赖 python-dotenv
from PIL import Image  # noqa: E402


@dataclass
class ModeResult:
    similarities: list[float] = field(default_factory=list)
    latency_ms: list[float] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0})

    @property
    def mean(self) -> float:
        return sum(self.similarities) / max(1, len(self.similarities))


def _degrade(image: Image.Image) -> Image.Image:
    """合成图太干净：旋 1.5° + 高斯模糊 + 降采样回升，模拟手机实拍的画质损失。

    真实瓶颈机制：整页大图喂 VLM 会被等比缩放入模，单题像素骤降；
    切题子图小、不受缩放影响——退化后该差距应被放大（对齐 Phase 0 实拍结论）。
    """
    from PIL import ImageFilter

    degraded = image.rotate(1.5, resample=Image.BICUBIC, fillcolor="white")
    degraded = degraded.filter(ImageFilter.GaussianBlur(1.1))
    w, h = degraded.size
    degraded = degraded.resize((int(w * 0.62), int(h * 0.62)), Image.LANCZOS)
    return degraded.resize((w, h), Image.LANCZOS)


def _normalize(text: str) -> str:
    return "".join(text.split())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _pick(dotenv: dict[str, str], *names: str) -> str | None:
    import os

    for name in names:
        value = dotenv.get(name) or os.environ.get(name)
        if value:
            return value
    return None


async def _transcribe(
    *, provider: str, base_url: str, api_key: str, model: str, prompt_text: str, image_path: Path
) -> tuple[str, object]:
    response = await chat_completions(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(str(image_path))}},
                ],
            }
        ],
        timeout=120.0,
    )
    return response.content.strip(), response


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=API_DIR / "tests/fixtures/two_page_spread.png")
    parser.add_argument("--truth", type=Path, default=API_DIR / "tests/fixtures/two_page_spread.truth.json")
    parser.add_argument("--provider", default="doubao", choices=["doubao", "qwen_vl"])
    parser.add_argument("--model", default=None, help="覆盖默认模型名")
    parser.add_argument("--prefer-dotenv", action="store_true", help="wengu-api/.env 优先于进程环境变量")
    parser.add_argument(
        "--degrade",
        action="store_true",
        help="对图片先做旋转/模糊/降采样退化（模拟手机实拍画质，公平对比两模式）",
    )
    args = parser.parse_args()

    dotenv = dotenv_values(API_DIR / ".env") if args.prefer_dotenv else {}
    if args.provider == "doubao":
        api_key = _pick(dotenv, "WENGU_DOUBAO_API_KEY", "ARK_API_KEY")
        base_url = (
            _pick(dotenv, "WENGU_DOUBAO_BASE_URL", "ARK_BASE_URL")
            or "https://ark.cn-beijing.volces.com/api/v3"
        )
        model = (
            args.model
            or _pick(dotenv, "WENGU_DOUBAO_MODEL_VALUE")
            or "doubao-seed-2-1-lite-260915"
        )
    else:
        api_key = _pick(dotenv, "WENGU_QWEN_API_KEY", "DASHSCOPE_API_KEY")
        base_url = (
            _pick(dotenv, "WENGU_QWEN_BASE_URL", "DASHSCOPE_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        model = args.model or _pick(dotenv, "WENGU_QWEN_MODEL_VALUE") or "qwen-vl-max"
    if not api_key:
        raise SystemExit(f"缺少 {args.provider} 的 API key（写入 wengu-api/.env 或环境变量）")

    prompt = load_prompts(API_DIR.parent / "llm_prompts")["transcribe_image"]
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    expected_per_question = [
        (f"{q['anchor']} {q['text']}" if q.get("anchor") else q["text"])
        for q in truth["questions"]
    ]
    expected_all = "\n".join(expected_per_question)

    print(f"image={args.image.name} provider={args.provider} model={model} prompt={prompt.id}@{prompt.version}")

    started = time.perf_counter()
    source = args.image
    if args.degrade:
        degraded_path = Path(tempfile.mkdtemp(prefix="wengu-eval-")) / "degraded.png"
        with Image.open(args.image) as original:
            _degrade(original.convert("RGB")).save(degraded_path, format="PNG")
        source = degraded_path
        print("已应用画质退化（旋转1.5°+模糊+62%降采样回升）")
    lines = get_ocr_engine().detect_lines(source)
    with Image.open(source) as im:
        plan = plan_slices(lines, im.size)
        tmp = Path(tempfile.mkdtemp(prefix="wengu-eval-"))
        crops: list[Path] = []
        for s in plan.slices:
            out = tmp / f"crop-{s.seq:02d}.png"
            im.crop(s.bbox).save(out, format="PNG")
            crops.append(out)
    ocr_ms = (time.perf_counter() - started) * 1000
    print(f"本地切片: {len(lines)} 行 → {len(crops)} 题 ({ocr_ms:.0f}ms, 书缝={plan.column_split_x})")

    async def run_mode(mode: str, images: list[Path]) -> ModeResult:
        result = ModeResult()
        for path in images:
            text, resp = await _transcribe(
                provider=args.provider,
                base_url=base_url,
                api_key=api_key,
                model=model,
                prompt_text=prompt.template,
                image_path=path,
            )
            result.latency_ms.append(resp.latency_ms)
            result.usage["input"] += resp.usage.input_tokens
            result.usage["output"] += resp.usage.output_tokens
            if mode == "whole":
                result.similarities.append(_similarity(text, expected_all))
            else:
                idx = len(result.similarities)
                expected = expected_per_question[idx] if idx < len(expected_per_question) else ""
                result.similarities.append(_similarity(text, expected))
        return result

    whole = await run_mode("whole", [source])
    sliced = await run_mode("sliced", crops)

    def _fmt(result: ModeResult) -> str:
        lat = sorted(result.latency_ms)
        return (
            f"相似度均分 {result.mean:.3f}  (min {min(result.similarities):.3f} / max {max(result.similarities):.3f})"
            f" | 延迟 p50 {lat[len(lat)//2]:.0f}ms"
            f" | tokens in={result.usage['input']} out={result.usage['output']}"
        )

    print(f"整页直读 ×1 : {_fmt(whole)}")
    print(f"切题逐题 ×{len(crops)}: {_fmt(sliced)}")
    delta = sliced.mean - whole.mean
    verdict = "切题显著占优" if delta > 0.05 else ("基本持平" if abs(delta) <= 0.05 else "整页占优（需复核）")
    print(f"结论: Δ={delta:+.3f} → {verdict}")
    print("注: 开发者脚本不经 gateway，不记 model_runs；usage 见上表。")


if __name__ == "__main__":
    asyncio.run(main())
