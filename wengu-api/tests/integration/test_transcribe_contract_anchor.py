"""P5-8 行为锚定：后端真实校验函数消费 transcribe 包同一批 fixtures。

不复制校验逻辑、不 import transcribe 包——只读 fixtures JSON，调用后端
validate_envelope / validate_and_normalize，把输出聚合成 fixtures 的 _expect 指标。
这样 transcribe/evals 的黄金样例同时锚定「包内纯标准库校验器」与「后端运行时权威」，
任一侧校验语义漂移都会让本测试变红（可证伪）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.services.ingestion import validate_and_normalize, validate_envelope

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = _REPO_ROOT / "transcribe" / "evals" / "fixtures"


def _metrics(payload: Any) -> dict[str, Any]:
    """把后端两个真实函数的输出聚合成与 fixtures _expect 同口径的指标。"""
    try:
        _channel, items = validate_envelope(payload)
    except ValueError:
        return {
            "envelope_rejected": True,
            "accepted": 0,
            "rejected": 0,
            "placeholder_count": 0,
            "incomplete_count": 0,
            "unknown_fields": 0,
        }
    result = validate_and_normalize(items)
    return {
        "envelope_rejected": False,
        "accepted": len(result.drafts),
        "rejected": len(result.errors),
        "placeholder_count": sum(1 for d in result.drafts if d["has_placeholder"]),
        "incomplete_count": sum(1 for d in result.drafts if d["is_incomplete"]),
        "unknown_fields": result.dropped_unknown_fields,
    }


def _load_cases() -> list[tuple[str, Any, dict[str, Any]]]:
    valid = json.loads((_FIXTURES / "valid_batch.json").read_text(encoding="utf-8"))
    expect = valid.pop("_expect")
    cases: list[tuple[str, Any, dict[str, Any]]] = [("valid_batch", valid, expect)]
    for case in json.loads((_FIXTURES / "invalid_cases.json").read_text(encoding="utf-8")):
        cases.append((case["name"], case["payload"], case["expect"]))
    return cases


_CASES = _load_cases()


@pytest.mark.integration
@pytest.mark.parametrize("name,payload,expect", _CASES, ids=[c[0] for c in _CASES])
def test_backend_matches_transcribe_fixtures(
    name: str, payload: Any, expect: dict[str, Any]
) -> None:
    actual = _metrics(payload)
    for key, want in expect.items():
        assert actual[key] == want, f"{name}: {key} 期望 {want} 实得 {actual[key]}"
