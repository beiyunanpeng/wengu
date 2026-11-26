"""P5-20 文档当前态守卫：head / 业务表数自述必须等于盘上派生值（纯文本 + ORM 元数据，不建库、不联网、不调子进程）。

守四件事：
A. 当前态锚点（目录结构.md / wengu-api/README.md 的 migrations/ 行、STATUS 头部快照行 + §4.8 / §5.2 锚点句）
   里出现的 revision 全名一律 == 盘上唯一 head，业务表数一律 == len(Base.metadata.tables)；
   §5.2 只取首行、且只扫首个「（」前的当前态声明（括注为历史来历，写旧 revision 全名属合法）；
B. 派生值自证：head 有同名迁移文件、表数与 test_migrations.EXPECTED_TABLES 互等（两个独立真源相互制约）；
C. §5.2 锚点句必须留 dictation_sheets / audio_ref / source 三条来历字面（防只改数字不留来历）；
D. 历史留痕反向钉住：CHANGELOG 旧 head 串计数与 deploy 升级表行不得被"顺手翻正"。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "wengu-api" / "migrations" / "versions"

_REVISION_RE = re.compile(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", re.M)
_DOWN_REVISION_RE = re.compile(r"^down_revision(?::[^=]+)?\s*=\s*(?:[\"']([^\"']+)[\"']|None)", re.M)
_HEAD_TOKEN_RE = re.compile(r"00\d{2}_[a-z0-9_]+")


def alembic_head() -> str:
    revisions: set[str] = set()
    referenced: set[str] = set()
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision_match = _REVISION_RE.search(text)
        assert revision_match, f"迁移文件缺 revision 字面：{path.name}"
        revisions.add(revision_match.group(1))
        down_match = _DOWN_REVISION_RE.search(text)
        if down_match and down_match.group(1):
            referenced.add(down_match.group(1))
    heads = sorted(revisions - referenced)
    assert len(heads) == 1, f"alembic head 必须唯一（分叉/多 head 即炸）：{heads}"
    return heads[0]


def business_table_count() -> int:
    import app.models  # noqa: F401  触发全部 ORM 表注册进 Base.metadata
    from app.core.database import Base

    return len(Base.metadata.tables)


def _expected_tables() -> set[str]:
    path = REPO_ROOT / "wengu-api" / "tests" / "integration" / "test_migrations.py"
    spec = importlib.util.spec_from_file_location("_p5_20_test_migrations", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EXPECTED_TABLES


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _migrations_line(relative: str) -> str:
    lines = [line for line in _read(relative).splitlines() if "migrations/" in line and "head" in line]
    assert len(lines) == 1, f"{relative} 的 migrations/ head 行必须唯一：{lines}"
    return lines[0]


def _status_line(prefix: str) -> str:
    lines = [line for line in _read("docs/STATUS.md").splitlines() if line.startswith(prefix)]
    assert len(lines) == 1, f"docs/STATUS.md 以 {prefix!r} 开头的行必须唯一：{lines}"
    return lines[0]


def _status_52_sentence() -> str:
    lines = [line for line in _read("docs/STATUS.md").splitlines() if line.startswith("- Alembic head `")]
    assert len(lines) == 1, f"docs/STATUS.md §5.2 锚点行必须唯一：{lines}"
    line = lines[0]
    assert "张业务表" in line, "§5.2 锚点句漂移：行内未找到业务表数"
    return line


def test_current_state_anchors_match_disk() -> None:
    head = alembic_head()
    count = business_table_count()
    anchors = {
        "目录结构.md migrations/ 行": _migrations_line("目录结构.md"),
        "wengu-api/README.md migrations/ 行": _migrations_line("wengu-api/README.md"),
        "docs/STATUS.md 头部快照行": _status_line("> Alembic head："),
        "docs/STATUS.md §4.8": _status_line("- SQLite WAL + Alembic（head"),
        # §5.2 只扫首个「（」前的当前态声明；括注是历史来历，允许写旧 revision 全名（P5-20 折入）
        "docs/STATUS.md §5.2": _status_52_sentence().split("（", 1)[0],
    }
    for label, text in anchors.items():
        tokens = _HEAD_TOKEN_RE.findall(text)
        assert tokens, f"{label} 未写 head 全名（裸数字不算）：{text}"
        for token in tokens:
            assert token == head, f"{label} 自述 head `{token}` != 盘上 head `{head}`"
    for label, text in anchors.items():
        for pattern in (r"(\d+) 张业务表", r"业务表 \*\*(\d+) 张\*\*"):
            for value in re.findall(pattern, text):
                assert int(value) == count, f"{label} 自述业务表 {value} 张 != 盘上 {count} 张"


def test_derived_values_self_check() -> None:
    head = alembic_head()
    assert (VERSIONS_DIR / f"{head}.py").is_file(), f"head `{head}` 找不到同名迁移文件"
    assert business_table_count() == len(_expected_tables()), "Base.metadata.tables 与 EXPECTED_TABLES 表数互等失败"


def test_section_52_provenance_literals() -> None:
    sentence = _status_52_sentence()
    for literal in ("dictation_sheets", "audio_ref", "source"):
        assert literal in sentence, f"§5.2 锚点句缺来历字面 `{literal}`"


def test_history_literals_not_rewritten() -> None:
    changelog = _read("CHANGELOG.md")
    assert changelog.count("head 仍 `0020_recitation`") == 4
    assert changelog.count("head 保持 `0021_pomodoro_sessions`") == 1
    assert changelog.count("head 推进到 `0022_correction_notes`") == 1
    assert changelog.count("head 推进到 `0023_learning_events_occurred_at`") == 1
    upgrade = _read("docs/deploy/upgrade-v0.5.0.md")
    assert "| alembic head | `0018_practice_dedup` | **`0020_recitation`** |" in upgrade
