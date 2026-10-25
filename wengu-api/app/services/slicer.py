"""切题纯函数：题号锚点 + 垂直间隙聚类 → 裁剪框（零模型、零引擎依赖）。

信号（对齐 TICKETS P1-3b）：
1. 题号锚点：`12.` `3、` `12．` `第5题` 等正则命中；分隔符后紧跟数字视为
   小数/千分位（1.5、1,234）排除。
2. 垂直间隙：行距 > GAP_FACTOR×行高中位数 → 无锚点题也切得开。
3. 双页平铺：中部横向带检出空白竖缝（书缝）→ 按栏各自聚类再拼序号。

铁律：0 锚点 → SliceError 明确失败（无锚点情况下不瞎切）。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from app.preprocess.ocr import TextLine

PADDING_PX = 8  # 裁剪框外扩边距
GAP_FACTOR = 2.0  # 行距 > 2.0×行高中位数 → 新题边界（题间空行通常 ≥1 倍行高）
GUTTER_SCAN = (0.35, 0.65)  # 双页检测在中部 35%–65% 横向带找空白竖缝
GUTTER_MIN_WIDTH = 0.02  # 竖缝至少占图宽 2% 才算书缝
MIN_SLICE_AREA = 400  # 小于此面积的组视为 OCR 噪声丢弃（px²；padding 后最小 256）


class SliceError(ValueError):
    """切题失败（如无锚点）——明确拒绝，绝不瞎切。"""


@dataclass(frozen=True)
class Slice:
    seq: int
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2（相对母图，钳制在图内）
    anchor_label: str | None  # 组首行命中的题号；间隙切出的组为 None


@dataclass(frozen=True)
class SlicePlan:
    slices: list[Slice]
    header_line_count: int  # 首锚点上方的页眉行数（丢弃计数，便于调参复核）
    column_split_x: int | None  # 双页书缝的 x 坐标；单栏为 None


_ANCHOR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(\d{1,2})\s*[.、．:：)](?!\d)"),
    re.compile(r"^\s*第\s*(\d{1,3})\s*题"),
)

_ANCHOR_LABEL_MAX = 20
# 题号上限：作业/试卷单页题号不可能超过 100（第999题 视为噪声）
_MAX_ANCHOR_NUMBER = 100


def anchor_label(text: str) -> str | None:
    for pattern in _ANCHOR_PATTERNS:
        m = pattern.match(text)
        if m and int(m.group(1)) <= _MAX_ANCHOR_NUMBER:
            return m.group(0).strip()[:_ANCHOR_LABEL_MAX]
    return None


def _sort_key(line: TextLine) -> tuple[int, int]:
    return ((line.box[1] + line.box[3]) // 2, line.box[0])


def _detect_gutter(lines: list[TextLine], width: int) -> int | None:
    """在中部横向带找最长空白竖缝；缝够宽判为双页书缝，返回缝中心 x。"""

    lo, hi = int(width * GUTTER_SCAN[0]), int(width * GUTTER_SCAN[1])
    diff = [0] * (width + 1)
    for line in lines:
        if line.box[2] < lo or line.box[0] > hi:
            continue  # 扫描带外的行不影响书缝判定
        x1 = max(lo, min(hi, line.box[0]))
        x2 = max(lo, min(hi, line.box[2]))
        diff[x1] += 1
        diff[x2 + 1] -= 1
    run_start: int | None = None
    best_start, best_len = 0, 0
    active = 0
    for x in range(lo, hi + 1):
        active += diff[x]
        if active == 0:
            if run_start is None:
                run_start = x
            if x - run_start + 1 > best_len:
                best_start, best_len = run_start, x - run_start + 1
        else:
            run_start = None
    if best_len >= max(2, int(width * GUTTER_MIN_WIDTH)):
        return best_start + best_len // 2
    return None


def _cluster_column(
    column: list[TextLine], image_size: tuple[int, int], start_seq: int
) -> tuple[list[Slice], int]:
    anchors = [i for i, line in enumerate(column) if anchor_label(line.text)]
    if not anchors:
        raise SliceError("未检测到题号锚点，拒绝切分（无锚点情况下不瞎切）")
    width, height = image_size
    median_h = statistics.median([line.height for line in column]) or 1

    groups: list[list[TextLine]] = []
    current: list[TextLine] = []
    for line in column[anchors[0] :]:
        if current and line.box[1] - current[-1].box[3] > GAP_FACTOR * median_h:
            groups.append(current)
            current = []
        current.append(line)
    if current:
        groups.append(current)

    slices: list[Slice] = []
    for group in groups:
        x1 = min(g.box[0] for g in group)
        y1 = min(g.box[1] for g in group)
        x2 = max(g.box[2] for g in group)
        y2 = max(g.box[3] for g in group)
        x1, y1 = max(0, x1 - PADDING_PX), max(0, y1 - PADDING_PX)
        x2, y2 = min(width, x2 + PADDING_PX), min(height, y2 + PADDING_PX)
        if (x2 - x1) * (y2 - y1) < MIN_SLICE_AREA:
            continue
        slices.append(
            Slice(
                seq=start_seq + len(slices),
                bbox=(x1, y1, x2, y2),
                anchor_label=anchor_label(group[0].text),
            )
        )
    return slices, anchors[0]


def plan_slices(lines: list[TextLine], image_size: tuple[int, int]) -> SlicePlan:
    if not lines:
        raise SliceError("OCR 未检测到任何文本行")
    width, _height = image_size

    split = _detect_gutter(lines, width)
    ordered = sorted(lines, key=_sort_key)
    columns: list[list[TextLine]]
    if split is None:
        columns = [ordered]
    else:
        left = [ln for ln in ordered if (ln.box[0] + ln.box[2]) // 2 < split]
        right = [ln for ln in ordered if (ln.box[0] + ln.box[2]) // 2 >= split]
        columns = [left, right] if left and right else [ordered]
        if len(columns) == 1:
            split = None

    slices: list[Slice] = []
    header_count = 0
    for column in columns:
        if not column:
            continue
        column_slices, first_anchor = _cluster_column(column, image_size, len(slices))
        header_count += first_anchor
        slices.extend(column_slices)
    if not slices:
        raise SliceError("聚类后没有任何可输出的题组")
    return SlicePlan(slices=slices, header_line_count=header_count, column_split_x=split)
