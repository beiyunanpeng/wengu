"""切题纯函数：题号锚点 + 垂直间隙聚类 → 裁剪框（零模型、零引擎依赖）。

信号（对齐 TICKETS P1-3b / P1-3c）：
1. 题号锚点：`12.` `3、` `12．` `第5题` 等正则命中；分隔符后紧跟数字视为
   小数/千分位（1.5、1,234）排除。**题号单调递增的锚点即新题边界**（密排试卷
   没有垂直间隙也切得开）；回退/重复题号视作作答行伪锚点（如手写"1.S"）。
2. 垂直间隙：行距 > GAP_FACTOR×行高中位数 → 无锚点题也切得开。
3. 双页平铺：中部横向带检出空白竖缝（书缝）→ 按栏各自聚类再拼序号。
4. 裁剪框（P1-3c）：本锚点到下一锚点之间的**整列块**（含配图、草稿与题间空白），
   左右按栏边界，末块收在文本下沿 + PADDING_PX；噪声仍按**文本并集面积**判。
5. 图注归属（P1-3c B1.5）：题干下方出现"第N题图"图注时，把本题块底扩到图注下沿
   ——图条可能排在后续题目之后；只认同栏、本题文本下方最近的同号图注，块间允许重叠。

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

# 图注：一行里可能并排多个，如"（第13题图）（第14题图）"
_CAPTION_PATTERN = re.compile(r"第\s*(\d{1,3})\s*题\s*图")

_ANCHOR_LABEL_MAX = 20
# 题号上限：作业/试卷单页题号不可能超过 100（第999题 视为噪声）
_MAX_ANCHOR_NUMBER = 100


def _anchor_match(text: str) -> tuple[int, str] | None:
    for pattern in _ANCHOR_PATTERNS:
        m = pattern.match(text)
        if m and int(m.group(1)) <= _MAX_ANCHOR_NUMBER:
            return int(m.group(1)), m.group(0).strip()[:_ANCHOR_LABEL_MAX]
    return None


def anchor_label(text: str) -> str | None:
    match = _anchor_match(text)
    return match[1] if match else None


def _figure_caption_bottom(
    column: list[TextLine], number: int, text_bottom: int
) -> int | None:
    """同栏、本题文本下方最近的"第N题图"图注下沿；无则 None。"""

    best: tuple[int, int] | None = None
    for line in column:
        if line.box[1] < text_bottom:
            continue
        if number not in {int(n) for n in _CAPTION_PATTERN.findall(line.text)}:
            continue
        if best is None or line.box[1] < best[0]:
            best = (line.box[1], line.box[3])
    return None if best is None else best[1]


def _anchor_boundaries(column: list[TextLine]) -> list[int]:
    """题号单调递增才认作新题首行：过滤作答行等伪锚点（如手写"1.S"）。"""

    boundaries: list[int] = []
    last_number = -1
    for index, line in enumerate(column):
        match = _anchor_match(line.text)
        if match is None or match[0] <= last_number:
            continue
        boundaries.append(index)
        last_number = match[0]
    return boundaries


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
    column: list[TextLine],
    image_size: tuple[int, int],
    start_seq: int,
    column_x: tuple[int, int],
) -> tuple[list[Slice], int]:
    boundaries = _anchor_boundaries(column)
    if not boundaries:
        raise SliceError("未检测到题号锚点，拒绝切分（无锚点情况下不瞎切）")
    width, height = image_size
    median_h = statistics.median([line.height for line in column]) or 1

    boundary_set = set(boundaries)
    groups: list[list[TextLine]] = []
    current: list[TextLine] = []
    for index in range(boundaries[0], len(column)):
        line = column[index]
        is_caption = bool(_CAPTION_PATTERN.search(line.text))
        if current and (
            index in boundary_set
            or (
                # 图注属于上方图条，不构成新题，不因间隙另起一组
                not is_caption
                and line.box[1] - current[-1].box[3] > GAP_FACTOR * median_h
            )
        ):
            groups.append(current)
            current = []
        current.append(line)
    if current:
        groups.append(current)

    text_boxes = [
        (
            min(g.box[0] for g in group),
            min(g.box[1] for g in group),
            max(g.box[2] for g in group),
            max(g.box[3] for g in group),
        )
        for group in groups
    ]
    # 噪声按文本并集面积判：块扩到整列宽后，小噪点会被整列框人为放大
    kept = [
        index
        for index, (tx1, ty1, tx2, ty2) in enumerate(text_boxes)
        if (tx2 - tx1) * (ty2 - ty1) >= MIN_SLICE_AREA
    ]
    x1 = max(0, column_x[0])
    x2 = min(width, column_x[1])

    slices: list[Slice] = []
    for pos, index in enumerate(kept):
        group = groups[index]
        _, ty1, _, ty2 = text_boxes[index]
        y1 = max(0, ty1 - PADDING_PX)
        y2 = (
            # 块底压到下一题首行上沿；crop 右下开区间，不含下一题像素
            min(height, text_boxes[kept[pos + 1]][1])
            if pos + 1 < len(kept)
            else min(height, ty2 + PADDING_PX)
        )
        anchor = _anchor_match(group[0].text)
        if anchor is not None:
            caption_bottom = _figure_caption_bottom(column, anchor[0], ty2)
            if caption_bottom is not None:
                # 图条可能排在后续题目之后：块底扩到图注下沿，块间允许重叠
                y2 = max(y2, min(height, caption_bottom + PADDING_PX))
        slices.append(
            Slice(
                seq=start_seq + len(slices),
                bbox=(x1, y1, x2, y2),
                anchor_label=anchor_label(group[0].text),
            )
        )
    return slices, boundaries[0]


def plan_slices(lines: list[TextLine], image_size: tuple[int, int]) -> SlicePlan:
    if not lines:
        raise SliceError("OCR 未检测到任何文本行")
    width, _height = image_size

    split = _detect_gutter(lines, width)
    ordered = sorted(lines, key=_sort_key)
    columns: list[tuple[list[TextLine], tuple[int, int]]]
    if split is None:
        columns = [(ordered, (0, width))]
    else:
        left = [ln for ln in ordered if (ln.box[0] + ln.box[2]) // 2 < split]
        right = [ln for ln in ordered if (ln.box[0] + ln.box[2]) // 2 >= split]
        if left and right:
            columns = [(left, (0, split)), (right, (split, width))]
        else:
            columns = [(ordered, (0, width))]
            split = None

    slices: list[Slice] = []
    header_count = 0
    for column, column_x in columns:
        if not column:
            continue
        column_slices, first_anchor = _cluster_column(
            column, image_size, len(slices), column_x
        )
        header_count += first_anchor
        slices.extend(column_slices)
    if not slices:
        raise SliceError("聚类后没有任何可输出的题组")
    return SlicePlan(slices=slices, header_line_count=header_count, column_split_x=split)
