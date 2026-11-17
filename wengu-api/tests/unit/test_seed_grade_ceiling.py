"""P5-9 学段作用域 `seed_grade_ceiling` 守卫（v2.8 §19-G）。

钉死的口径：
- 合法值只有字面枚举 {6, 9, 16}，默认 16 = 全量可见（现有安装零行为变化）；
- `knowledge_seed.grade` 是 Text 列：过滤必须 `cast(grade, Integer)`，
  字典序反例（'16' <= '9' 为真）是本票主锚点；
- grade NULL（家长自建点）一律保留；summary 与 topics 用同一把尺；
- 先修边 / loader 回溯索引不受 ceiling 收窄（ceiling 只管"能主动选什么"）；
- 过滤只发生在服务端：wengu-web/src 不得出现 ceiling 过滤逻辑，
  孩子区未解锁 GET /api/config 仍被 PIN 挡、列表端点照常收窄。
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.core.database import create_sqlite_engine, get_session
from app.core.runtime_config import (
    SEED_GRADE_CEILINGS,
    ConfigError,
    describe_config,
    save_config,
    seed_grade_ceiling,
    validate_updates,
)
from app.main import create_app
from app.models import KnowledgeSeed, PrerequisiteEdge
from app.seed.bank import BankQuestion, BankStats, QuestionBank
from app.seed.loader import load_seed
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 配置层（纯单测）：字面枚举、默认零变化、非法回退、热加载
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ceiling_constant_is_literal_enum() -> None:
    # §19-L 纪律①：右侧字面串，不引用被测常量之外的实现。
    assert set(SEED_GRADE_CEILINGS) == {6, 9, 16}


@pytest.mark.unit
def test_accepted_ints_are_exactly_the_literal_enum() -> None:
    """行为探针：-2..20 里被接受的整数集合必须恰为 {6, 9, 16}。

    变异"放开接受任意 int"→ accepted 变成整个区间 → 红。
    """

    accepted = set()
    for value in range(-2, 21):
        try:
            validate_updates({"seed_grade_ceiling": value})
        except ConfigError:
            continue
        accepted.add(value)
    assert accepted == {6, 9, 16}


@pytest.mark.unit
@pytest.mark.parametrize("value", [6, 9, 16])
def test_valid_ceiling_passes_whitelist(value: int) -> None:
    assert validate_updates({"seed_grade_ceiling": value}) == {
        "seed_grade_ceiling": value
    }


@pytest.mark.unit
@pytest.mark.parametrize("value", [7, 0, -6, 17, "9", True, 9.0, [9], None])
def test_invalid_ceiling_rejected_before_write(tmp_path, value) -> None:
    with pytest.raises(ConfigError):
        validate_updates({"seed_grade_ceiling": value})


@pytest.mark.unit
@pytest.mark.parametrize("value", [7, "9", 0, True, 9.0, [9]])
async def test_invalid_ceiling_save_writes_nothing(tmp_path, value) -> None:
    data_dir = tmp_path / "data"
    with pytest.raises(ConfigError):
        await save_config(
            SimpleNamespace(data_dir=data_dir),
            updates={"seed_grade_ceiling": value},
            project_root=tmp_path / "repo",
            env={},
        )
    assert not (data_dir / "app-config.json").exists()


@pytest.mark.unit
def test_default_ceiling_is_sixteen_when_key_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WENGU_APP_CONFIG", str(tmp_path / "missing.json"))
    assert seed_grade_ceiling() == 16


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["9", 7, 0, True, None, [9], 2.5, ""])
def test_invalid_file_value_falls_back_to_sixteen(tmp_path, monkeypatch, raw) -> None:
    path = tmp_path / "app-config.json"
    path.write_text(json.dumps({"seed_grade_ceiling": raw}), encoding="utf-8")
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))
    assert seed_grade_ceiling() == 16


@pytest.mark.unit
def test_ceiling_hot_reload_without_restart(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    path.write_text(json.dumps({"seed_grade_ceiling": 6}), encoding="utf-8")
    assert seed_grade_ceiling() == 6
    path.write_text(json.dumps({"seed_grade_ceiling": 9}), encoding="utf-8")
    assert seed_grade_ceiling() == 9
    path.write_text("{ broken json", encoding="utf-8")
    assert seed_grade_ceiling() == 16


@pytest.mark.unit
async def test_describe_and_save_roundtrip(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    description = describe_config()
    assert description["values"]["seed_grade_ceiling"] == 16
    assert description["sources"]["seed_grade_ceiling"] == "default"

    await save_config(updates={"seed_grade_ceiling": 9})
    assert json.loads(path.read_text(encoding="utf-8")) == {"seed_grade_ceiling": 9}
    description = describe_config()
    assert description["values"]["seed_grade_ceiling"] == 9
    assert description["sources"]["seed_grade_ceiling"] == "file"


@pytest.mark.unit
def test_frontend_source_has_no_ceiling_filter() -> None:
    """服务端过滤证明：src 里提到 ceiling 的只能是配置管道（types/SetupPage），
    且任何文件都不得把 ceiling 与 .filter( 放在一起（前端过滤 = 越权放宽）。"""

    src = ROOT / "wengu-web" / "src"
    mentioning: list[str] = []
    for path in sorted(src.rglob("*.ts")) + sorted(src.rglob("*.tsx")):
        text = path.read_text(encoding="utf-8")
        if "ceiling" not in text.lower():
            continue
        rel = path.relative_to(src).as_posix()
        mentioning.append(rel)
        assert ".filter(" not in text, f"{rel} 出现 ceiling 过滤逻辑"
    assert set(mentioning) <= {"api/types.ts", "pages/SetupPage.tsx"}
    for picker in ("components/CategoryPicker.tsx", "components/QuizTopicPicker.tsx"):
        assert "ceiling" not in (src / picker).read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------------------
# 端点层（集成）：字典序反例、同尺计数、NULL 保留、回溯不受限、PIN 边界
# ---------------------------------------------------------------------------

ROWS = [
    ("t_six", "数学", "小学点", "6"),
    ("t_nine", "数学", "初中点", "9"),
    ("t_sixteen", "数学", "高中点", "16"),
    ("t_null", "语文", "家长自建点", None),
]


def _settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "wengu.db",
        seeds_dir=tmp_path / "seeds",
    )


def _migrated(settings: Settings) -> async_sessionmaker:
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", f"sqlite:///{Path(settings.db_path).as_posix()}"
    )
    command.upgrade(config, "head")
    engine = create_sqlite_engine(Path(settings.db_path))
    return async_sessionmaker(engine, expire_on_commit=False)


def _use_ceiling(tmp_path: Path, monkeypatch, value: int | None) -> None:
    path = tmp_path / "app-config.json"
    if value is not None:
        path.write_text(json.dumps({"seed_grade_ceiling": value}), encoding="utf-8")
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))


@asynccontextmanager
async def _client(
    factory: async_sessionmaker,
    settings: Settings,
    monkeypatch,
    *,
    unlock: bool = False,
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(
        "app.api.seed.get_settings", lambda: SimpleNamespace(seeds_dir=settings.seeds_dir)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if unlock:
            response = await client.post("/api/session/pin/set", json={"pin": "2468"})
            assert response.status_code == 200, response.text
        yield client


async def _insert_rows(factory: async_sessionmaker, rows=ROWS) -> None:
    async with factory() as session, session.begin():
        for topic_id, subject, name, grade in rows:
            session.add(
                KnowledgeSeed(
                    id=topic_id,
                    subject=subject,
                    name=name,
                    grade=grade,
                    unaudited=True,
                    blind_verified=False,
                )
            )


def _question(topic_id: str) -> BankQuestion:
    return BankQuestion(
        id=f"{topic_id}_q1",
        topic_id=topic_id,
        subject="数学",
        type="numeric",
        difficulty=None,
        prompt="1+1=?",
        answer="2",
        accept=(),
        choices=(),
        unordered=False,
        hide_choice_text=False,
        figure=None,
        explanation="",
        verify=None,
        verify_status="unverifiable",
        verify_reason=None,
        percent=False,
        unaudited=True,
        blind_verified=False,
    )


def _stub_bank(monkeypatch, grades: dict[str, object], with_questions: set[str]) -> None:
    """把 quizzes 端点看到的运行时题库换成受控小池（services 层禁改，桩打在 api 绑定上）。"""

    questions = {tid: _question(tid) for tid in with_questions}
    bank = QuestionBank(
        by_topic={tid: (questions[tid],) for tid in with_questions},
        by_id={q.id: q for q in questions.values()},
        topics={
            tid: {"id": tid, "subject": "数学", "name": tid, "grade": grade}
            for tid, grade in grades.items()
        },
        stats=BankStats(total=len(questions)),
    )

    async def fake_runtime_bank(session):
        return bank

    monkeypatch.setattr("app.api.quizzes.get_runtime_bank", fake_runtime_bank)


async def _topic_ids(client: AsyncClient, url: str) -> set[str]:
    response = await client.get(url, params={"limit": 200})
    assert response.status_code == 200, response.text
    body = response.json()
    key = "topic_id" if "quizzes" in url else "id"
    return {item[key] for item in body["items"]}


@pytest.mark.integration
async def test_lexicographic_counterexample_requires_cast(tmp_path, monkeypatch) -> None:
    """主锚点：grade "9" 与 "16" 并存，ceiling=9 时 "16" 必须不在、"9" 必须在。

    变异：去掉 func.cast 退字符串比较 → SQLite 字典序 '16' <= '9' 为真 →
    t_sixteen 泄漏进两个列表 → 本用例红。
    """

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    await _insert_rows(factory)
    _use_ceiling(tmp_path, monkeypatch, 9)
    _stub_bank(
        monkeypatch,
        {tid: grade for tid, _, _, grade in ROWS},
        {tid for tid, _, _, _ in ROWS},
    )

    async with _client(factory, settings, monkeypatch) as client:
        seed_ids = await _topic_ids(client, "/api/seed/topics")
        quiz_ids = await _topic_ids(client, "/api/quizzes/topics")

    for ids in (seed_ids, quiz_ids):
        assert "t_sixteen" not in ids
        assert "t_nine" in ids
        assert "t_six" in ids
        assert "t_null" in ids


@pytest.mark.integration
async def test_summary_and_topics_share_one_yardstick(tmp_path, monkeypatch) -> None:
    """计数同尺 + 独立重算：每个 ceiling 下 summary.topics_total == topics.total，
    且都等于按 DB 行独立重算的期望（不写死期望值迁就实现）。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    await _insert_rows(factory)
    async with factory() as session, session.begin():
        session.add(
            PrerequisiteEdge(parent_id="t_six", child_id="t_nine", edge_type="hard")
        )

    async with _client(factory, settings, monkeypatch) as client:
        for ceiling in (6, 9, 16):
            _use_ceiling(tmp_path, monkeypatch, ceiling)
            expected = [
                (subject, grade)
                for _, subject, _, grade in ROWS
                if grade is None or int(grade) <= ceiling
            ]
            summary = (await client.get("/api/seed/summary")).json()
            topics = (await client.get("/api/seed/topics", params={"limit": 200})).json()
            assert summary["topics_total"] == topics["total"] == len(expected)
            assert summary["subjects"] == {
                subject: {
                    "topics": count,
                    "unaudited": count,
                    "blind_verified": 0,
                }
                for subject, count in Counter(s for s, _ in expected).items()
            }
            # 先修边总数不受 ceiling 收窄（回溯面全量）。
            assert summary["edges_total"] == 1


@pytest.mark.integration
async def test_default_ceiling_changes_nothing(tmp_path, monkeypatch) -> None:
    """默认零变化：不写该键时三个面的读数 == 全量独立重算（= 合并前行为）。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    await _insert_rows(factory)
    _use_ceiling(tmp_path, monkeypatch, None)
    _stub_bank(
        monkeypatch,
        {tid: grade for tid, _, _, grade in ROWS},
        {tid for tid, _, _, _ in ROWS},
    )

    async with _client(factory, settings, monkeypatch) as client:
        summary = (await client.get("/api/seed/summary")).json()
        topics = (await client.get("/api/seed/topics", params={"limit": 200})).json()
        quiz = (await client.get("/api/quizzes/topics", params={"limit": 200})).json()

    all_ids = {tid for tid, _, _, _ in ROWS}
    assert summary["topics_total"] == len(ROWS)
    assert topics["total"] == len(ROWS)
    assert {item["id"] for item in topics["items"]} == all_ids
    assert quiz["total"] == len(ROWS)
    assert {item["topic_id"] for item in quiz["items"]} == all_ids
    assert summary["subjects"] == {
        subject: {"topics": count, "unaudited": count, "blind_verified": 0}
        for subject, count in Counter(s for _, s, _, _ in ROWS).items()
    }


@pytest.mark.integration
async def test_null_grade_survives_ceiling_six(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    await _insert_rows(factory)
    _use_ceiling(tmp_path, monkeypatch, 6)
    _stub_bank(
        monkeypatch,
        {tid: grade for tid, _, _, grade in ROWS},
        {tid for tid, _, _, _ in ROWS},
    )

    async with _client(factory, settings, monkeypatch) as client:
        seed_ids = await _topic_ids(client, "/api/seed/topics")
        quiz_ids = await _topic_ids(client, "/api/quizzes/topics")

    assert seed_ids == {"t_six", "t_null"}
    assert quiz_ids == {"t_six", "t_null"}


@pytest.mark.integration
async def test_backtrace_and_edges_not_limited_by_ceiling(tmp_path, monkeypatch) -> None:
    """回溯不受限（DoD 双断言）+ 越界点的先修链仍完整。

    口径说明：ceiling=9 = 小学+初中，小学点本就在选择范围内；要让
    "前置路径仍返回小学点、而它不出现在 quiz_topics" 同时成立，该小学点
    必须是**无题可组**的前置根因点（quiz_topics 只列有题的点）。
    另钉：高中点（16，越界）的先修链在 loader 索引里照常可走。
    """

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    seeds_dir = tmp_path / "seeds"
    (seeds_dir / "data").mkdir(parents=True)
    (seeds_dir / "data" / "topics.json").write_text(
        json.dumps(
            [
                {"id": "junior", "subject": "数学", "name": "初中点", "grade": 9},
                {"id": "primary", "subject": "数学", "name": "小学根因点", "grade": 6},
                {"id": "senior", "subject": "数学", "name": "高中点", "grade": 16},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (seeds_dir / "data" / "dependencies.json").write_text(
        json.dumps(
            [
                {"topic_id": "junior", "prerequisite_id": "primary", "strength": "hard"},
                {"topic_id": "senior", "prerequisite_id": "junior", "strength": "hard"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    async with factory() as session:
        index = await load_seed(session, seeds_dir, data_dir=tmp_path / "runtime")

    _use_ceiling(tmp_path, monkeypatch, 9)
    # primary 无题（前置根因点）；junior/senior 有题。
    _stub_bank(
        monkeypatch,
        {"junior": "9", "primary": "6", "senior": "16"},
        {"junior", "senior"},
    )

    async with _client(factory, settings, monkeypatch) as client:
        quiz_ids = await _topic_ids(client, "/api/quizzes/topics")
        summary = (await client.get("/api/seed/summary")).json()
        seed_ids = await _topic_ids(client, "/api/seed/topics")

        # 双断言同时成立：前置路径仍返回小学点，而它不出现在 quiz_topics。
        assert index.prerequisites_of("junior") == ["primary"]
        assert "primary" not in quiz_ids
        # 越界高中点的先修链不受 ceiling 影响；边总数全量。
        assert index.prerequisites_of("senior") == ["junior"]
        assert summary["edges_total"] == 2
        # 选择面：初中在、高中被 ceiling 挡、小学根因点仍在 seed 列表（可挂载）。
        assert quiz_ids == {"junior"}
        assert seed_ids == {"junior", "primary"}

        # ceiling 收到 6：索引回溯依旧完整（ceiling 不进 loader/边表）。
        _use_ceiling(tmp_path, monkeypatch, 6)
        assert index.prerequisites_of("junior") == ["primary"]
        assert (await _topic_ids(client, "/api/seed/topics")) == {"primary"}

    async with factory() as session:
        kept = await session.scalar(
            select(func.count()).select_from(KnowledgeSeed).where(KnowledgeSeed.id == "primary")
        )
    assert kept == 1, "ceiling 不得删改已装载的知识点行"


@pytest.mark.integration
async def test_lower_stage_stays_selectable_within_ceiling(tmp_path, monkeypatch) -> None:
    """§19-G：上限式不是学段硬隔离——ceiling=9 时小学点有题就仍可主动选。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    await _insert_rows(factory)
    _use_ceiling(tmp_path, monkeypatch, 9)
    _stub_bank(
        monkeypatch,
        {tid: grade for tid, _, _, grade in ROWS},
        {tid for tid, _, _, _ in ROWS},
    )

    async with _client(factory, settings, monkeypatch) as client:
        quiz_ids = await _topic_ids(client, "/api/quizzes/topics")
    assert "t_six" in quiz_ids
    assert "t_sixteen" not in quiz_ids


@pytest.mark.integration
async def test_config_pin_gate_while_lists_narrow_server_side(tmp_path, monkeypatch) -> None:
    """孩子区未解锁：GET/PUT /api/config 仍 403，而列表端点照常按 ceiling 收窄
    ——证明收窄不依赖前端读配置。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    await _insert_rows(factory)
    _use_ceiling(tmp_path, monkeypatch, 6)
    _stub_bank(
        monkeypatch,
        {tid: grade for tid, _, _, grade in ROWS},
        {tid for tid, _, _, _ in ROWS},
    )

    async with _client(factory, settings, monkeypatch, unlock=False) as client:
        assert (await client.get("/api/config")).status_code == 403
        assert (
            await client.put("/api/config", json={"seed_grade_ceiling": 16})
        ).status_code == 403
        assert await _topic_ids(client, "/api/seed/topics") == {"t_six", "t_null"}
        assert await _topic_ids(client, "/api/quizzes/topics") == {"t_six", "t_null"}


@pytest.mark.integration
async def test_put_ceiling_enum_validation_over_http(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    _use_ceiling(tmp_path, monkeypatch, None)
    config_path = tmp_path / "app-config.json"

    async with _client(factory, settings, monkeypatch, unlock=True) as client:
        for payload in (
            {"seed_grade_ceiling": 7},
            {"seed_grade_ceiling": "9"},
            {"seed_grade_ceiling": 0},
            {"seed_grade_ceiling": True},
            {"seed_grade_ceiling": 9.0},
            {"seed_grade_ceiling": [9]},
            {"seed_grade_ceiling": None},
            {"seed_grade_ceiling": 17},
        ):
            response = await client.put("/api/config", json=payload)
            assert response.status_code == 422, (payload, response.text)
            assert not config_path.exists(), "非法值不得写盘"

        for value in (6, 9, 16):
            response = await client.put("/api/config", json={"seed_grade_ceiling": value})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["values"]["seed_grade_ceiling"] == value
            assert body["sources"]["seed_grade_ceiling"] == "file"
            assert seed_grade_ceiling() == value
