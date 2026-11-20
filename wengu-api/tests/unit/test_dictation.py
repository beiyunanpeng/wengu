"""P3-4 默写纯函数：词序固化、回录校验、状态机、卷面零 answer（定案⑤）。

answer 零泄漏三层断言：
1. 卷面投影 dataclass 与 API schema 都没有 answer 字段；
2. 打印页源码不出现 answer 字样（仓内前端测试是 node --test 纯逻辑、无 DOM
   设施，组件级断言以源码守卫代替，交付时单列复核点）；
3. GET 响应级断言在 tests/integration/test_dictation_api.py。
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from app.api.recitations import (
    RecordResultsResponse,
    SheetDetailResponse,
    SheetItemView,
    SheetResultView,
    SheetView,
)
from app.models import RecitationItem
from app.services.dictation import (
    MAX_SHEET_ITEMS,
    SHEET_OPEN,
    SHEET_RECORDED,
    SheetItem,
    ensure_open,
    normalize_item_ids,
    project_items,
    validate_results,
)
from app.services.recitation import RecitationConflict, RecitationInvalid, decide

DAY = date(2026, 11, 20)
REPO_ROOT = Path(__file__).resolve().parents[3]


def _item(item_id: int, prompt: str, *, status: str = "active") -> RecitationItem:
    return RecitationItem(
        id=item_id,
        subject="英语",
        prompt=prompt,
        answer=f"{prompt} 的释义",
        unit="U1",
        status=status,
        created_by="parent",
        created_at=datetime(2026, 11, 20, 8, 0, 0),
    )


def test_normalize_item_ids_keeps_submission_order() -> None:
    assert normalize_item_ids([7, 2, 9]) == (7, 2, 9)


def test_normalize_item_ids_rejects_empty_duplicate_and_non_positive() -> None:
    with pytest.raises(RecitationInvalid):
        normalize_item_ids([])
    with pytest.raises(RecitationInvalid):
        normalize_item_ids([3, 3])
    with pytest.raises(RecitationInvalid):
        normalize_item_ids([0])
    with pytest.raises(RecitationInvalid):
        normalize_item_ids([-1])
    with pytest.raises(RecitationInvalid):
        normalize_item_ids([True])
    with pytest.raises(RecitationInvalid):
        normalize_item_ids(["3"])  # type: ignore[list-item]


def test_normalize_item_ids_caps_sheet_size() -> None:
    """边界两侧钉手写字面值（§19-L）：常量调大或 > 写成 >= 都必须红。"""

    assert MAX_SHEET_ITEMS == 200
    assert normalize_item_ids(list(range(1, 201))) == tuple(range(1, 201))
    with pytest.raises(RecitationInvalid):
        normalize_item_ids(list(range(1, 202)))


def test_validate_results_reorders_into_sheet_order() -> None:
    ordered = validate_results(
        [5, 2, 8], [(8, "forgot"), (5, "remembered"), (2, "remembered")]
    )
    assert ordered == ((5, "remembered"), (2, "remembered"), (8, "forgot"))


def test_validate_results_allows_partial_coverage() -> None:
    assert validate_results([5, 2, 8], [(2, "forgot")]) == ((2, "forgot"),)


def test_validate_results_rejects_foreign_duplicate_empty_and_third_verdict() -> None:
    with pytest.raises(RecitationInvalid):
        validate_results([1, 2], [(3, "remembered")])
    with pytest.raises(RecitationInvalid):
        validate_results([1, 2], [(1, "remembered"), (1, "forgot")])
    with pytest.raises(RecitationInvalid):
        validate_results([1, 2], [])
    with pytest.raises(RecitationInvalid):
        validate_results([1, 2], [(1, "uncertain")])


def test_ensure_open_is_one_way_state_machine() -> None:
    ensure_open(SHEET_OPEN)
    with pytest.raises(RecitationConflict):
        ensure_open(SHEET_RECORDED)


def test_project_items_keeps_order_and_lists_missing() -> None:
    items = {item.id: item for item in (_item(5, "abandon"), _item(2, "banana"))}
    views, missing = project_items([2, 9, 5], items)
    assert [view.item_id for view in views] == [2, 5]
    assert [view.prompt for view in views] == ["banana", "abandon"]
    assert missing == (9,)


def test_sheet_projection_and_schemas_have_no_answer_field() -> None:
    assert {field.name for field in fields(SheetItem)} == {
        "item_id",
        "prompt",
        "unit",
        "status",
    }
    for schema in (
        SheetView,
        SheetItemView,
        SheetDetailResponse,
        SheetResultView,
        RecordResultsResponse,
    ):
        assert "answer" not in schema.model_fields


def test_print_dictation_page_source_never_mentions_answer() -> None:
    source = (
        REPO_ROOT / "wengu-web" / "src" / "pages" / "PrintDictationSheetPage.tsx"
    ).read_text(encoding="utf-8")
    assert "answer" not in source.lower()


def test_dictation_reuses_decide_unchanged() -> None:
    """批量回录的调度内核就是 decide()：逐档字面值与单条自评同一把尺。"""

    assert decide(0, "remembered", DAY).rung == 1
    assert decide(0, "remembered", DAY).scheduled_next == DAY + timedelta(days=3)
    assert decide(1, "forgot", DAY).rung == 1
    assert decide(1, "forgot", DAY).scheduled_next == DAY + timedelta(days=3)
    top = decide(4, "remembered", DAY)
    assert top.rung == 4
    assert top.scheduled_next is None
    assert top.graduated is True
