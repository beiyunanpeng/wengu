"""生成 P1-3b 切题测试 fixture：双页平铺合成图 + ground truth（开发者一次性跑）。

用法：venv/Scripts/python scripts/make_slicing_fixture.py
产出到 tests/fixtures/：
- two_page_spread.png   双页合成图（左栏 6 题组含页眉/间隙组，右栏 4 题组含多行题）
- two_page_spread.truth.json  期望切片数/锚点序列/各题文本（eval_slicing 打分用）

需要系统 CJK 字体（Windows: msyh/simhei/simsun）；CI/容器直接用提交好的 PNG，
无需字体。渲染确定性：无随机，坐标全部写死。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

API_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = API_DIR / "tests" / "fixtures"

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

FONT_SIZE = 26
LINE_H = 44
CANVAS_W, CANVAS_H = 2300, 1560
LEFT_X, RIGHT_X = 70, 1270  # 书缝位于 x≈1060–1240，扫描带内为空白
PAGE_TOP = 50

# (x_offset, y, text)；同一题的多行紧排（行距 52 < 间隙阈值），题间空一行以上
LEFT_LINES = [
    (LEFT_X, PAGE_TOP, "初一数学同步练习（10月24日）"),
    (LEFT_X, 140, "1. 计算：(-3)+5=______"),
    (LEFT_X, 290, "2. 解方程 2x+3=7"),
    (LEFT_X, 440, "3、化简：3a+2a-a"),
    (LEFT_X, 640, "4．已知 |a|=2，则 a=______"),
    (LEFT_X, 840, "答：a=±2，过程见下"),
    (LEFT_X, 1060, "第5题 求 y=2x-1 与 x 轴交点"),
]
RIGHT_LINES = [
    (RIGHT_X, PAGE_TOP, "初二数学提高训练"),
    (RIGHT_X, 140, "1. 计算：根号16-根号9=______"),
    (RIGHT_X, 290, "2. 分解因式：x^2-4=______"),
    (RIGHT_X, 440, "3. 在三角形ABC中，角C=90度，"),
    (RIGHT_X, 492, "AC=3，BC=4，求 AB 的长"),
    (RIGHT_X, 680, "4. 解不等式组"),
    (RIGHT_X, 732, "(1) x>1"),
    (RIGHT_X, 784, "(2) x≤3"),
]

# ground truth：按期望切片顺序（左栏自上而下 → 右栏自上而下）
TRUTH_QUESTIONS = [
    {"anchor": "1.", "text": "计算：(-3)+5=______"},
    {"anchor": "2.", "text": "解方程 2x+3=7"},
    {"anchor": "3、", "text": "化简：3a+2a-a"},
    {"anchor": "4．", "text": "已知 |a|=2，则 a=______"},
    {"anchor": None, "text": "答：a=±2，过程见下"},
    {"anchor": "第5题", "text": "求 y=2x-1 与 x 轴交点"},
    {"anchor": "1.", "text": "计算：根号16-根号9=______"},
    {"anchor": "2.", "text": "分解因式：x^2-4=______"},
    {"anchor": "3.", "text": "在三角形ABC中，角C=90度，AC=3，BC=4，求 AB 的长"},
    {"anchor": "4.", "text": "解不等式组 (1) x>1 (2) x≤3"},
]


def _load_font() -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), FONT_SIZE)
    raise SystemExit("未找到 CJK 字体，请在本机（Windows）运行后提交 PNG")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    font = _load_font()

    image = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    draw = ImageDraw.Draw(image)
    for x, y, text in LEFT_LINES + RIGHT_LINES:
        draw.text((x, y), text, fill="black", font=font)
    png_path = OUT_DIR / "two_page_spread.png"
    image.save(png_path, format="PNG")

    # 无锚点页：通篇无题号，切片必须明确失败（禁止无锚点瞎切）
    no_anchor = Image.new("RGB", (1200, 620), "white")
    na_draw = ImageDraw.Draw(no_anchor)
    for i, text in enumerate(
        [
            "今天天气很好适合复习数学",
            "昨天错了三道题需要认真重做",
            "明天考试要准备好草稿纸",
            "记得把错题本带给老师检查",
        ]
    ):
        na_draw.text((60, 60 + i * 130), text, fill="black", font=font)
    na_path = OUT_DIR / "no_anchor_page.png"
    no_anchor.save(na_path, format="PNG")

    truth = {
        "image": png_path.name,
        "canvas": [CANVAS_W, CANVAS_H],
        "min_slices": len(TRUTH_QUESTIONS),
        "questions": TRUTH_QUESTIONS,
    }
    truth_path = OUT_DIR / "two_page_spread.truth.json"
    truth_path.write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"fixture: {png_path.name} ({png_path.stat().st_size} bytes)")
    print(f"fixture: {na_path.name} ({na_path.stat().st_size} bytes)")
    print(f"truth:   {truth_path.name} ({len(TRUTH_QUESTIONS)} 题组)")
    print(f"canvas:  {CANVAS_W}x{CANVAS_H}, gutter≈1060..1240")


if __name__ == "__main__":
    sys.exit(main())
