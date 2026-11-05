"""P0-5：`conftest.pytest_configure` 清理 Windows 死链接的逻辑回归。

本机与 CI 都不允许真建符号链接（权限不足正是这条噪音的成因），所以整条链路打桩：
- `_pytest_temp_root()` 指向 `tmp_path` 下的沙盒根，绝不读写真实 `%TEMP%`；
- `Path.is_symlink` / `Path.resolve` 只对沙盒里的 `pytest-current` 返回“坏链接”；
- `os.rmdir` / `os.rename` 用计数桩，成功与失败两条分支都能覆盖。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import conftest
import pytest


def _config(basetemp: Path | None = None) -> SimpleNamespace:
    return SimpleNamespace(option=SimpleNamespace(basetemp=basetemp))


def _sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, healthy: bool = False) -> tuple[Path, Path]:
    root = tmp_path / "pytest-of-roc"
    root.mkdir()
    link = root / "pytest-current"
    link.write_text("placeholder")
    real_is_symlink = Path.is_symlink
    real_resolve = Path.resolve

    def fake_is_symlink(self: Path) -> bool:
        return True if self == link else real_is_symlink(self)

    def fake_resolve(self: Path, strict: bool = False) -> object:
        if self == link:
            return SimpleNamespace(exists=lambda: healthy)
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    monkeypatch.setattr(Path, "resolve", fake_resolve)
    monkeypatch.setattr(conftest, "_pytest_temp_root", lambda: root)
    monkeypatch.setattr(sys, "platform", "win32")
    return root, link


def _count_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:
    calls: dict[str, list[object]] = {"rmdir": [], "rename": []}
    monkeypatch.setattr(os, "rmdir", lambda path: calls["rmdir"].append(path))
    monkeypatch.setattr(os, "rename", lambda src, dst: calls["rename"].append((src, dst)))
    return calls


def test_dead_link_is_removed_in_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, link = _sandbox(monkeypatch, tmp_path)
    rmdir_calls: list[Path] = []
    rename_calls: list[tuple[Path, Path]] = []

    def fake_rmdir(path: str | os.PathLike[str]) -> None:
        rmdir_calls.append(Path(path))
        os.remove(path)  # 桩负责真正删掉替身文件

    monkeypatch.setattr(os, "rmdir", fake_rmdir)
    monkeypatch.setattr(os, "rename", lambda src, dst: rename_calls.append((src, dst)))

    conftest.pytest_configure(_config())

    assert rmdir_calls == [link]
    assert not link.exists()
    assert root.exists()
    assert rename_calls == []
    assert "[p0-5]" not in capsys.readouterr().err


def test_unremovable_link_moves_temp_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, link = _sandbox(monkeypatch, tmp_path)
    rmdir_calls: list[Path] = []
    rename_calls: list[tuple[Path, Path]] = []
    real_rename = os.rename

    def failing_rmdir(path: str | os.PathLike[str]) -> None:
        rmdir_calls.append(Path(path))
        raise PermissionError(13, "拒绝访问。")

    def fake_rename(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        rename_calls.append((Path(src), Path(dst)))
        real_rename(src, dst)

    monkeypatch.setattr(os, "rmdir", failing_rmdir)
    monkeypatch.setattr(os, "rename", fake_rename)

    conftest.pytest_configure(_config())

    assert rmdir_calls == [link]
    assert len(rename_calls) == 1
    src, dst = rename_calls[0]
    assert src == root
    assert re.fullmatch(r"pytest-of-roc\.stale-\d{8}-\d{6}-\d+", dst.name)
    assert not root.exists()
    assert dst.exists()
    assert f"[p0-5] cannot remove {link}; moved temp root to {dst} for this run" in capsys.readouterr().err


def test_guard_skips_when_basetemp_given(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _sandbox(monkeypatch, tmp_path)
    calls = _count_calls(monkeypatch)

    conftest.pytest_configure(_config(basetemp=tmp_path / "given"))

    assert calls["rmdir"] == []
    assert calls["rename"] == []


def test_guard_skips_off_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    calls = _count_calls(monkeypatch)

    conftest.pytest_configure(_config())

    assert calls["rmdir"] == []
    assert calls["rename"] == []


def test_guard_skips_healthy_link(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _sandbox(monkeypatch, tmp_path, healthy=True)
    calls = _count_calls(monkeypatch)

    conftest.pytest_configure(_config())

    assert calls["rmdir"] == []
    assert calls["rename"] == []
