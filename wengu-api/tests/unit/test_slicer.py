"""切题纯函数单测：锚点正则 / 聚类 / 双栏 gutter / 钳制 / 无锚点拒绝。

全部用手搓 TextLine，不依赖 OCR 引擎（引擎行为在集成测试覆盖）。
"""

from __future__ import annotations

import pytest
from app.preprocess.ocr import TextLine
from app.services.slicer import SliceError, anchor_label, plan_slices


def line(x1: int, y1: int, x2: int, y2: int, text: str) -> TextLine:
    return TextLine(box=(x1, y1, x2, y2), text=text, score=0.99)


def test_anchor_label_forms() -> None:
    assert anchor_label("12. 计算") == "12."
    assert anchor_label("3、化简") == "3、"
    assert anchor_label("4．已知") == "4．"
    assert anchor_label("12) 选择") == "12)"
    assert anchor_label("第5题 求") == "第5题"
    assert anchor_label("第100题 阅读") == "第100题"
    assert anchor_label("  8.  跳格也认") == "8."


def test_anchor_label_rejects_decimals_and_plain_text() -> None:
    assert anchor_label("1.5 是小数") is None  # 分隔符后紧跟数字
    assert anchor_label("1,234 是千分位") is None
    assert anchor_label("第999题 超出范围") is None
    assert anchor_label("abc 普通文字") is None
    assert anchor_label("① 圈号不是题号") is None
    assert anchor_label("(1) 括号项") is None


def test_dense_page_splits_at_anchors_without_gaps() -> None:
    lines = [
        line(10, 100, 600, 130, "1. 第一题"),
        line(10, 130, 600, 160, "2. 第二题"),
        line(10, 160, 600, 190, "3. 第三题"),
    ]
    plan = plan_slices(lines, (800, 600))
    assert plan.column_split_x is None
    assert [s.anchor_label for s in plan.slices] == ["1.", "2.", "3."]
    # 密排无间隙也要一题一块：每块只覆盖本题一行
    assert [s.bbox[1] for s in plan.slices] == [92, 122, 152]


def test_non_increasing_anchor_is_not_a_boundary() -> None:
    lines = [
        line(10, 100, 600, 130, "1. 第一题"),
        line(10, 130, 600, 160, "2. 第二题"),
        line(600, 160, 640, 190, "1.S"),  # 手写作答行误命中题号正则
        line(10, 190, 600, 220, "3. 第三题"),
    ]
    plan = plan_slices(lines, (800, 600))
    assert [s.anchor_label for s in plan.slices] == ["1.", "2.", "3."]
    # 伪锚点行留在上一题组内，不单独成块
    assert plan.slices[1].bbox[3] >= 190


def test_single_column_clusters_with_header_and_gap() -> None:
    lines = [
        line(10, 0, 300, 30, "页眉：练习卷"),
        line(10, 100, 200, 130, "1. 第一题"),
        line(10, 200, 200, 230, "2. 第二题首行"),
        line(10, 250, 220, 280, "第二题次行紧排"),
        # 大间隙 + 无锚点 → 独立组，label 为 None
        line(10, 500, 220, 530, "答：略"),
    ]
    plan = plan_slices(lines, (800, 600))
    assert plan.column_split_x is None
    assert plan.header_line_count == 1
    assert [s.seq for s in plan.slices] == [0, 1, 2]
    assert [s.anchor_label for s in plan.slices] == ["1.", "2.", None]
    # 多行题合并为一组：组 1 的 bbox 覆盖两行
    assert plan.slices[1].bbox[1] < 250 and plan.slices[1].bbox[3] > 280


def test_two_page_gutter_splits_columns() -> None:
    lines = [
        line(50, 50, 250, 80, "左页页眉"),
        line(50, 200, 150, 230, "1. 左一"),
        line(50, 350, 150, 380, "2. 左二"),
        line(1250, 50, 1450, 80, "右页页眉"),
        line(1250, 200, 1350, 230, "1. 右一"),
        line(1250, 350, 1350, 380, "2. 右二"),
    ]
    plan = plan_slices(lines, (2000, 1000))
    assert plan.column_split_x is not None
    assert plan.header_line_count == 2
    # 序号全局连续：左栏 0,1 → 右栏 2,3
    assert [s.seq for s in plan.slices] == [0, 1, 2, 3]
    assert [s.anchor_label for s in plan.slices] == ["1.", "2.", "1.", "2."]
    left_x = [s.bbox[0] for s in plan.slices[:2]]
    right_x = [s.bbox[0] for s in plan.slices[2:]]
    assert all(x < 1000 for x in left_x) and all(x > 1000 for x in right_x)


def test_zero_anchors_rejected() -> None:
    lines = [line(10, i * 100, 300, i * 100 + 30, f"普通段落第{i}行") for i in range(3)]
    with pytest.raises(SliceError, match="不瞎切"):
        plan_slices(lines, (800, 400))


def test_empty_lines_rejected() -> None:
    with pytest.raises(SliceError, match="未检测到任何文本行"):
        plan_slices([], (800, 600))


def test_bbox_clamped_to_image() -> None:
    lines = [line(0, 0, 799, 599, "1. 贴边大题")]
    plan = plan_slices(lines, (800, 600))
    x1, y1, x2, y2 = plan.slices[0].bbox
    assert x1 == 0 and y1 == 0 and x2 <= 800 and y2 <= 600


def test_tiny_noise_group_dropped() -> None:
    lines = [
        line(10, 100, 400, 130, "1. 正常题"),
        line(10, 300, 13, 303, "2. 噪点"),  # 面积 9 < MIN_SLICE_AREA
    ]
    plan = plan_slices(lines, (800, 600))
    assert len(plan.slices) == 1
    assert plan.slices[0].anchor_label == "1."
