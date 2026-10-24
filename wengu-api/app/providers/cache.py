"""内容哈希三级缓存的 L1（内存）+ L2（data/ai-cache/*.json）。

L3（data/ai-raw/{date}/ 原始上游响应）由 gateway 在真实调用后落盘，不在本模块。
信封只含模型/prompt 版本/结果/用量/时间——不含题目全文之外的输入原文；
输入以哈希进 key，相同输入+相同模型+相同 prompt 版本 → 命中即零成本复用。
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple | list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def make_cache_key(
    *,
    task: str,
    provider: str,
    model: str,
    prompt_id: str,
    prompt_version: int,
    payload: dict[str, Any],
) -> str:
    """payload 必须是已摘要化的可 JSON 数据（图片=sha256 十六进制，文本=原串）。"""

    blob = json.dumps(
        {
            "task": task,
            "provider": provider,
            "model": model,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "payload": payload,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def hash_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ContentHashCache:
    """L1 OrderedDict（容量淘汰）→ L2 磁盘 JSON（原子写，进程重启后仍命中）。"""

    def __init__(self, l2_dir: Path, *, max_l1: int = 256) -> None:
        self._l2_dir = Path(l2_dir)
        self._l2_dir.mkdir(parents=True, exist_ok=True)
        self._max_l1 = max_l1
        self._l1: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = Lock()

    def _put_l1(self, key: str, envelope: dict[str, Any]) -> None:
        with self._lock:
            self._l1[key] = envelope
            self._l1.move_to_end(key)
            while len(self._l1) > self._max_l1:
                self._l1.popitem(last=False)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            envelope = self._l1.get(key)
            if envelope is not None:
                self._l1.move_to_end(key)
                return envelope
        path = self._l2_dir / f"{key}.json"
        if not path.is_file():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        if not isinstance(envelope, dict) or "result" not in envelope:
            return None
        self._put_l1(key, envelope)
        return envelope

    def set(
        self,
        key: str,
        *,
        model: str,
        prompt_version: int,
        result: Any,
        usage: dict[str, Any],
    ) -> dict[str, Any]:
        envelope = {
            "model": model,
            "prompt_version": prompt_version,
            "result": _jsonable(result),
            "usage": usage,
            "created_at": datetime.now(UTC).isoformat(),
        }
        path = self._l2_dir / f"{key}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)  # 原子发布，读端永不拿到半截文件
        self._put_l1(key, envelope)
        return envelope
