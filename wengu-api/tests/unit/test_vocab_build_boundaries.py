"""P6-1 构建期边界：词表脚本不进 CI，运行时依赖集合不得回潮。"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_REQUIREMENTS = {
    "fastapi",
    "uvicorn",
    "python-multipart",
    "sqlalchemy",
    "alembic",
    "aiosqlite",
    "pydantic",
    "pydantic-settings",
    "bleach",
    "cryptography",
    "sympy",
    "apscheduler",
    "structlog",
    "pytest",
    "pytest-asyncio",
    "httpx",
    "ruff",
    "pip-licenses",
}


def _requirement_names() -> set[str]:
    names = set()
    for raw in (REPO_ROOT / "wengu-api" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        assert match, f"requirements 行无法解析：{raw}"
        names.add(match.group(1).lower())
    return names


def test_ci_never_runs_vocab_builder() -> None:
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "CI 工作流不能为空"
    for path in workflows:
        assert "import_vocab" not in path.read_text(encoding="utf-8"), path


def test_runtime_requirements_are_exact_literal_set() -> None:
    assert _requirement_names() == EXPECTED_REQUIREMENTS


def test_builder_never_rewrites_curated_source() -> None:
    script = (REPO_ROOT / "wengu-api" / "scripts" / "import_vocab.py").read_text(encoding="utf-8")
    assert '_write_json(out_dir / "_source_vocab.json"' not in script
