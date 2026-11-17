"""P5-10 全量收录守卫（v2.8 §19-G-1）：分桶字面 / 初中面零变化 / 转录目录不扩 / 回溯复活。

钉死的口径（§19-L 纪律①：右侧字面串，不从被测文件反算期望值）：
- 同一快照 d58785ce 全量收录：topics 1821（450/664/707）、deps 2917、questions 7431（1800/2803/2828）；
- 初中面零变化 = 初中子集字面与扩段前一致（664 点 / 1018 边 / 2803 题、学科分布不变）；
  ⚠️ ceiling=9 的**总数**必然 +450（ceiling 语义是 grade≤9 = 小学+初中），
  "初中面零变化"指 grade 7–9 子集的读数逐字相同，不是 ceiling9 总数不变；
- 转录目录维持初中-scoped：TSV 仍 665 行（表头 1 + 初中 664；含 1 条 local 行即 1+664+1）；
  删导出脚本过滤必须变红（变异守卫）；
- 回溯复活：真实初中→小学边（cne_j001→cne_p001）在 loader 索引可走、
  edges_total=2917 不受 ceiling 影响、该小学点有题在 ceiling9 下仍可主动组卷；
- blind_verified 只给初中数学（315 点）——扩段不得伪造质量标签；
- 策展 counts.load_quality 与 load_bank 实测一致，verify_mismatch 丢弃数必须为 0。
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
from app.core.config import Settings
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.seed.bank import load_bank
from app.seed.loader import load_seed
from httpx import ASGITransport, AsyncClient
from scripts import export_topics_junior
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "seeds"
DATA = SEEDS / "data"


def _read_json(name: str) -> list[dict]:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _band(grade: int) -> str:
    if grade <= 6:
        return "primary"
    if grade <= 9:
        return "junior"
    return "senior"


# ---------------------------------------------------------------------------
# 数据层（纯单测）：分桶字面、初中面字面、质量标签、策展 counts 自洽
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_full_snapshot_band_buckets() -> None:
    topics = _read_json("topics.json")
    deps = _read_json("dependencies.json")
    questions = _read_json("questions.json")
    grade = {t["id"]: t["grade"] for t in topics}

    assert len(topics) == 1821
    assert Counter(_band(t["grade"]) for t in topics) == {
        "primary": 450, "junior": 664, "senior": 707,
    }
    assert len(deps) == 2917
    assert len(questions) == 7431
    assert Counter(_band(grade[q["topic_id"]]) for q in questions) == {
        "primary": 1800, "junior": 2803, "senior": 2828,
    }
    # 全量后所有点都有题（回溯到学校根因点也能主动组卷的前提）
    assert {q["topic_id"] for q in questions} == set(grade)


@pytest.mark.unit
def test_junior_face_literals_unchanged() -> None:
    """初中子集字面 == 扩段前快照（构建期已另证 byte-identical，见交付报告）。"""

    topics = _read_json("topics.json")
    deps = _read_json("dependencies.json")
    questions = _read_json("questions.json")
    grade = {t["id"]: t["grade"] for t in topics}
    junior = [t for t in topics if _band(t["grade"]) == "junior"]

    assert len(junior) == 664
    assert Counter(t["subject"] for t in junior) == {"数学": 315, "英语": 257, "物理": 92}
    assert sum(
        1 for d in deps
        if _band(grade[d["topic_id"]]) == _band(grade[d["prerequisite_id"]]) == "junior"
    ) == 1018
    junior_q = [q for q in questions if _band(grade[q["topic_id"]]) == "junior"]
    assert len(junior_q) == 2803
    assert Counter(q["subject"] for q in junior_q) == {"数学": 1407, "物理": 368, "英语": 1028}


@pytest.mark.unit
def test_quality_labels_not_fabricated_for_new_bands() -> None:
    topics = _read_json("topics.json")
    assert all(t["unaudited"] is True for t in topics)
    blind = [t for t in topics if t["blind_verified"]]
    assert len(blind) == 315
    assert all(t["subject"] == "数学" and _band(t["grade"]) == "junior" for t in blind)


@pytest.mark.unit
def test_curated_quality_counts_match_load_bank() -> None:
    """策展 counts.load_quality 必须与 load_bank 实测一致；mismatch 丢弃数钉死 0。"""

    stats = load_bank(SEEDS).stats
    source = json.loads((DATA / "questions_source.json").read_text(encoding="utf-8"))
    quality = source["counts"]["load_quality"]

    assert stats.dropped == {}
    assert quality["full"]["verify_mismatch_dropped"] == 0
    assert quality["newly_added"]["verify_mismatch_dropped"] == 0
    assert quality["full"]["verified"] == stats.verified == 5996
    assert quality["full"]["unverifiable"] == stats.unverifiable == 1435
    assert quality["full"]["figures"] == stats.figures == 267
    assert quality["full"]["unverifiable_reasons"] == stats.verify_reasons
    assert quality["junior_baseline"] == {
        "verified": 1738, "unverifiable": 1065, "verify_mismatch_dropped": 0, "figures": 76,
    }
    added = quality["newly_added"]
    assert added["questions"] == 4628
    assert added["verified"] == 5996 - 1738
    assert added["unverifiable"] == 1435 - 1065
    assert added["figures"] == 267 - 76

    seed_source = json.loads((DATA / "_source.json").read_text(encoding="utf-8"))
    assert seed_source["counts"]["topics_imported"] == 1821
    assert seed_source["counts"]["dependencies_imported"] == 2917
    assert seed_source["counts"]["dependencies_dropped_cross_boundary"] == 0


# ---------------------------------------------------------------------------
# 转录目录（纯单测）：初中-scoped 不继承 import_seed 收录范围 + 删过滤变异必红
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tsv_stays_junior_scoped(tmp_path: Path) -> None:
    out = tmp_path / "topics_junior.tsv"
    by_subject = export_topics_junior.export(export_topics_junior.DEFAULT_SRC, out)

    assert by_subject == {"数学": 315, "物理": 92, "英语": 257}
    lines = out.read_text(encoding="utf-8").splitlines()
    # 无 local 自建点时 = 表头 1 + 初中 664 行（test_local_seed 的 1+664+1 含 1 条 local 行）
    assert len(lines) == 1 + 664
    assert lines[0].split("\t") == [
        "topic_id", "subject", "grade", "semester", "name", "domain", "chapter",
    ]
    for line in lines[1:]:
        assert line.split("\t")[2] in {"7", "8", "9"}, line
    assert not out.read_bytes().startswith(b"\xef\xbb\xbf")
    # 仓库内分发的 TSV 与脚本重跑输出逐字一致（输出不变的自证）
    assert out.read_bytes() == export_topics_junior.DEFAULT_OUT.read_bytes()


@pytest.mark.unit
def test_removing_export_filter_turns_tsv_guard_red(tmp_path: Path, monkeypatch) -> None:
    """变异守卫：把 _in_junior_catalog 换成恒真（= 删掉过滤），
    上一个测试钉死的 665 行 / grade∈7-9 立刻不成立——证明守卫对过滤敏感。"""

    monkeypatch.setattr(export_topics_junior, "_in_junior_catalog", lambda topic: True)
    out = tmp_path / "topics_junior.tsv"
    export_topics_junior.export(export_topics_junior.DEFAULT_SRC, out)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 + 1821
    assert any(line.split("\t")[2] == "3" for line in lines[1:])


# ---------------------------------------------------------------------------
# 端点层（集成，真实 seed + 临时库）：回溯复活 / edges 全量 / ceiling9 初中面恒等
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        data_dir=data_dir, db_path=data_dir / "wengu.db", seeds_dir=SEEDS,
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
    factory: async_sessionmaker, settings: Settings, monkeypatch
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(
        "app.api.seed.get_settings", lambda: SimpleNamespace(seeds_dir=SEEDS)
    )
    bank = load_bank(SEEDS)

    async def fake_runtime_bank(session):
        return bank

    monkeypatch.setattr("app.api.quizzes.get_runtime_bank", fake_runtime_bank)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _all_items(client: AsyncClient, url: str) -> tuple[int, list[dict]]:
    items: list[dict] = []
    offset = 0
    while True:
        response = await client.get(url, params={"limit": 200, "offset": offset})
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body["items"])
        offset += len(body["items"])
        if not body["items"] or offset >= body["total"]:
            return body["total"], items


def _junior_rows(items: list[dict]) -> list[dict]:
    return sorted(
        (item for item in items if item.get("grade") in {"7", "8", "9"}),
        key=lambda item: item.get("topic_id") or item.get("id"),
    )


def _junior_quiz_rows(items: list[dict], grade_of: dict[str, int]) -> list[dict]:
    # quiz_topics 的 grade 投影只认 str（_optional），真实 bank meta 是 int → None；
    # 初中归属按数据文件 grade 判定，payload 本身仍逐字比对。
    return sorted(
        (item for item in items if 7 <= grade_of[item["topic_id"]] <= 9),
        key=lambda item: item["topic_id"],
    )


@pytest.mark.integration
async def test_real_backtrace_revives_primary_under_ceiling9(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    async with factory() as session:
        index = await load_seed(session, SEEDS, data_dir=tmp_path / "runtime")

    grade_of = {t["id"]: t["grade"] for t in _read_json("topics.json")}

    # 真实初中→小学边（快照内 74 条之一）：回溯链完整，ceiling 不进 loader。
    assert "cne_p001" in index.prerequisites_of("cne_j001")

    _use_ceiling(tmp_path, monkeypatch, 9)
    async with _client(factory, settings, monkeypatch) as client:
        summary = (await client.get("/api/seed/summary")).json()
        assert summary["edges_total"] == 2917
        assert summary["topics_total"] == 1114
        assert {s: v["topics"] for s, v in summary["subjects"].items()} == {
            "数学": 557, "英语": 465, "物理": 92,
        }

        seed_total, seed_items = await _all_items(client, "/api/seed/topics")
        quiz_total, quiz_items = await _all_items(client, "/api/quizzes/topics")
        assert seed_total == quiz_total == 1114
        # 小学根因点有题 → ceiling9 下仍可主动组卷（上限式不是学段硬隔离）
        assert "cne_p001" in {item["topic_id"] for item in quiz_items}
        assert "cne_p001" in {item["id"] for item in seed_items}
        # 越界高中点不可选
        assert all(grade_of[item["topic_id"]] <= 9 for item in quiz_items)

        nine_seed_junior = _junior_rows(seed_items)
        nine_quiz_junior = _junior_quiz_rows(quiz_items, grade_of)

    _use_ceiling(tmp_path, monkeypatch, 16)
    async with _client(factory, settings, monkeypatch) as client:
        summary16 = (await client.get("/api/seed/summary")).json()
        assert summary16["edges_total"] == 2917
        assert summary16["topics_total"] == 1821
        seed_total16, seed_items16 = await _all_items(client, "/api/seed/topics")
        quiz_total16, quiz_items16 = await _all_items(client, "/api/quizzes/topics")
        assert seed_total16 == quiz_total16 == 1821

    # 初中面零变化：ceiling9 与默认 16 的 grade7–9 子集读数逐字相同，
    # 且子集规模 == 扩段前字面（664 点；学科分布 315/257/92）。
    assert _junior_rows(seed_items16) == nine_seed_junior
    assert _junior_quiz_rows(quiz_items16, grade_of) == nine_quiz_junior
    assert len(nine_seed_junior) == len(nine_quiz_junior) == 664
    assert Counter(item["subject"] for item in nine_seed_junior) == {
        "数学": 315, "英语": 257, "物理": 92,
    }
