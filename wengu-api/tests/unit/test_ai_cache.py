"""内容哈希缓存：key 稳定性、L1/L2 行为、信封编码。"""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.base import TokenUsage
from app.providers.cache import ContentHashCache, hash_bytes, make_cache_key


@dataclass(frozen=True)
class _Dummy:
    text: str
    score: float
    tags: tuple[str, ...]


def test_cache_key_is_stable_and_sensitive() -> None:
    base = dict(
        task="grade",
        provider="doubao",
        model="m",
        prompt_id="grade",
        prompt_version=1,
        payload={"problem_text": "1+1", "student_answer": "2"},
    )
    key1 = make_cache_key(**base)
    key2 = make_cache_key(**{**base, "payload": {"problem_text": "1+1", "student_answer": "2"}})
    assert key1 == key2

    assert make_cache_key(**{**base, "prompt_version": 2}) != key1  # 改 prompt 版本必失效
    assert make_cache_key(**{**base, "model": "m2"}) != key1
    assert make_cache_key(
        **{**base, "payload": {"problem_text": "1+2", "student_answer": "2"}}
    ) != key1


def test_hash_bytes_matches_file(tmp_path) -> None:
    blob = b"fake-image"
    path = tmp_path / "a.png"
    path.write_bytes(blob)
    from app.providers.cache import hash_file

    assert hash_file(path) == hash_bytes(blob)


def test_l1_then_l2_persistence(tmp_path) -> None:
    cache = ContentHashCache(tmp_path / "l2", max_l1=2)
    key = make_cache_key(
        task="grade",
        provider="doubao",
        model="m",
        prompt_id="grade",
        prompt_version=1,
        payload={"a": "1"},
    )
    assert cache.get(key) is None

    envelope = cache.set(
        key,
        model="m",
        prompt_version=1,
        result=_Dummy(text="x", score=0.5, tags=("a", "b")),
        usage=TokenUsage(input_tokens=1, output_tokens=2).__dict__,
    )
    assert envelope["result"] == {"text": "x", "score": 0.5, "tags": ["a", "b"]}
    assert envelope["usage"]["output_tokens"] == 2

    # 同一实例 L1 命中
    assert cache.get(key) == envelope

    # 新实例（模拟重启）L2 磁盘命中
    fresh = ContentHashCache(tmp_path / "l2", max_l1=2)
    assert fresh.get(key) == envelope


def test_l1_eviction_and_corrupt_l2(tmp_path) -> None:
    cache = ContentHashCache(tmp_path / "l2", max_l1=2)
    keys = [
        make_cache_key(
            task="t", provider="p", model="m", prompt_id="i", prompt_version=1, payload={"k": n}
        )
        for n in range(3)
    ]
    for key in keys:
        cache.set(key, model="m", prompt_version=1, result={"v": key[:8]}, usage={})
    assert cache.get(keys[0]) is not None  # L1 满后最老的被淘汰，但仍可从 L2 读回

    corrupt = tmp_path / "l2" / "bad.json"
    corrupt.write_text("not-json{{{", encoding="utf-8")
    assert cache.get("bad") is None
