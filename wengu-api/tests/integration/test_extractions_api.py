"""P1-4 提取端点集成测试：闸门落库、幂等、force、整页兜底、级联清理。

模型一律用 FakeGateway（零网络、零密钥）；真实 VLM 质量由 scripts/eval_extraction.py 负责。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import PhotoCapture, PhotoCaptureItem, ProblemExtraction
from app.providers.base import CallMeta, ExtractedProblem
from app.providers.registry import ProviderConfigError
from app.services.ai_gateway import get_ai_gateway
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
FIXTURES = API_DIR / "tests" / "fixtures"


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "extraction.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


def _seq_from_path(image_path: str) -> int:
    suffix = Path(image_path).stem.rsplit("-", 1)[-1]
    return int(suffix) if suffix.isdigit() else 0


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.generation = 1
        self.outcomes: dict[int, ExtractedProblem] = {}
        self.errors: dict[int, Exception] = {}
        self.default_error: Exception | None = None

    async def extract_problem(
        self, image_path: str, *, prompt_id: str = "extract_problem"
    ) -> tuple[ExtractedProblem, CallMeta]:
        self.calls.append(image_path)
        seq = _seq_from_path(image_path)
        if seq in self.errors:
            raise self.errors[seq]
        if self.default_error is not None:
            raise self.default_error
        extracted = self.outcomes.get(seq) or ExtractedProblem(
            problem_text=f"{seq + 1}. 题目第{self.generation}次",
            student_answer="2",
            confidence=0.9,
            problem_complete=True,
        )
        return extracted, CallMeta(
            provider="fake",
            model="fake-v1",
            latency_ms=1,
            prompt_id=prompt_id,
            prompt_version=1,
        )


def _make_client(factory: async_sessionmaker, tmp_path: Path, monkeypatch, gateway):
    uploads_dir = tmp_path / "uploads"
    app = create_app()
    fake_settings = lambda: SimpleNamespace(uploads_dir=uploads_dir)  # noqa: E731

    async def override_session():
        async with factory() as session:
            yield session

    monkeypatch.setattr("app.api.captures.get_settings", fake_settings)
    monkeypatch.setattr("app.api.extractions.get_settings", fake_settings)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_ai_gateway] = lambda: gateway
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), uploads_dir


async def _seed_capture(
    factory: async_sessionmaker, uploads_dir: Path, *, item_count: int = 0
) -> int:
    now = datetime.now(UTC)
    capture_rel = "pages/page.png"
    (uploads_dir / capture_rel).parent.mkdir(parents=True, exist_ok=True)
    (uploads_dir / capture_rel).write_bytes(b"fake-png")
    async with factory() as session, session.begin():
        capture = PhotoCapture(
            sha256=uuid4().hex,
            stored_path=capture_rel,
            original_name="page.png",
            source="phone",
            status="sliced" if item_count else "pending",
            created_at=now,
        )
        session.add(capture)
        await session.flush()
        for seq in range(item_count):
            rel = f"slices/x-{seq:02d}.png"
            (uploads_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (uploads_dir / rel).write_bytes(b"fake-png")
            session.add(
                PhotoCaptureItem(
                    photo_capture_id=capture.id,
                    seq=seq,
                    stored_path=rel,
                    bbox_json="[0, 0, 10, 10]",
                    anchor_label=str(seq + 1),
                    created_at=now,
                )
            )
        capture_id = capture.id
    return capture_id


async def _row_count(factory: async_sessionmaker) -> int:
    async with factory() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(ProblemExtraction)
            )
        )


@pytest.mark.integration
async def test_extract_slices_applies_gate_and_get_is_query_only(
    tmp_path, monkeypatch
) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    gateway.outcomes = {
        1: ExtractedProblem(
            problem_text="2. 已知〔?〕，求 x", student_answer="3", problem_complete=True
        ),
        2: ExtractedProblem(
            problem_text="3. 解方程 2x=4", student_answer=None, problem_complete=True
        ),
        3: ExtractedProblem(
            problem_text="4. 如图，求 AB 的长", student_answer="5", problem_complete=True
        ),
    }
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        capture_id = await _seed_capture(
            factory, tmp_path / "uploads", item_count=4
        )
        response = await client.post(f"/api/captures/{capture_id}/extract")
        get_response = await client.get(f"/api/captures/{capture_id}/extractions")

    assert response.status_code == 200
    body = response.json()
    assert body["source_kind"] == "slice"
    assert body["total"] == 4
    assert body["extracted_count"] == 4
    assert body["skipped_count"] == 0
    assert body["failed_count"] == 0
    statuses = [row["gate_status"] for row in body["results"]]
    assert statuses == [
        "ready_for_grading",
        "manual_review",
        "manual_review",
        "figure_dependent",
    ]
    assert "placeholder" in body["results"][1]["review_reasons"]
    assert "student_answer_empty" in body["results"][2]["review_reasons"]
    assert body["results"][3]["figure_keywords"] == ["如图"]
    assert all(row["prompt_id"] == "extract_problem" for row in body["results"])
    assert all(row["prompt_version"] == 1 for row in body["results"])

    calls_after_post = len(gateway.calls)
    assert get_response.status_code == 200
    assert get_response.json()["results"] == body["results"]
    assert len(gateway.calls) == calls_after_post  # GET 零模型调用
    assert await _row_count(factory) == 4


@pytest.mark.integration
async def test_extract_is_idempotent_and_force_replaces(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        capture_id = await _seed_capture(
            factory, tmp_path / "uploads", item_count=3
        )
        first = (await client.post(f"/api/captures/{capture_id}/extract")).json()
        second = (await client.post(f"/api/captures/{capture_id}/extract")).json()
        gateway.generation = 2
        forced = (
            await client.post(
                f"/api/captures/{capture_id}/extract", params={"force": "true"}
            )
        ).json()

    assert first["extracted_count"] == 3
    assert second["extracted_count"] == 0
    assert second["skipped_count"] == 3
    assert len(gateway.calls) == 6  # 首次 3 + force 3；幂等那次零调用
    assert forced["extracted_count"] == 3
    assert all("第2次" in row["problem_text"] for row in forced["results"])
    assert await _row_count(factory) == 3  # force 替换不叠加


@pytest.mark.integration
async def test_force_partial_failure_keeps_previous_result(
    tmp_path, monkeypatch
) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        capture_id = await _seed_capture(
            factory, tmp_path / "uploads", item_count=3
        )
        await client.post(f"/api/captures/{capture_id}/extract")
        gateway.generation = 2
        gateway.errors[1] = RuntimeError("boom")
        forced = (
            await client.post(
                f"/api/captures/{capture_id}/extract", params={"force": "true"}
            )
        ).json()

    assert forced["extracted_count"] == 2
    assert forced["failed_count"] == 1
    assert forced["errors"] == [{"seq": 1, "reason": "boom"}]
    by_seq = {row["seq"]: row for row in forced["results"]}
    assert "第2次" in by_seq[0]["problem_text"]
    assert "第1次" in by_seq[1]["problem_text"]  # 失败项保留旧结果
    assert await _row_count(factory) == 3


@pytest.mark.integration
async def test_retry_only_runs_missing_items(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    gateway.errors[1] = RuntimeError("temporary")
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        capture_id = await _seed_capture(
            factory, tmp_path / "uploads", item_count=3
        )
        first = (await client.post(f"/api/captures/{capture_id}/extract")).json()
        gateway.errors.clear()
        second = (await client.post(f"/api/captures/{capture_id}/extract")).json()

    assert first["extracted_count"] == 2
    assert first["failed_count"] == 1
    assert second["extracted_count"] == 1
    assert second["skipped_count"] == 2
    assert len(gateway.calls) == 4  # 3 + 只补失败的一题
    assert await _row_count(factory) == 3


@pytest.mark.integration
async def test_whole_page_fallback_routes_to_manual(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        capture_id = await _seed_capture(factory, tmp_path / "uploads")
        response = await client.post(f"/api/captures/{capture_id}/extract")
        get_response = await client.get(f"/api/captures/{capture_id}/extractions")

    body = response.json()
    assert response.status_code == 200
    assert body["source_kind"] == "whole_page"
    assert body["total"] == 1
    assert body["results"][0]["seq"] == 1
    assert body["results"][0]["item_id"] is None
    assert body["results"][0]["gate_status"] == "manual_review"
    assert "whole_page_unsegmented" in body["results"][0]["review_reasons"]
    assert get_response.json()["source_kind"] == "whole_page"


@pytest.mark.integration
async def test_missing_crop_files_are_reported_without_model_calls(
    tmp_path, monkeypatch
) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        capture_id = await _seed_capture(
            factory, tmp_path / "uploads", item_count=3
        )
        (tmp_path / "uploads" / "slices" / "x-01.png").unlink()
        partial = (await client.post(f"/api/captures/{capture_id}/extract")).json()

    assert partial["extracted_count"] == 2
    assert partial["failed_count"] == 1
    assert partial["errors"] == [{"seq": 1, "reason": "image_missing"}]
    assert len(gateway.calls) == 2


@pytest.mark.integration
async def test_all_files_missing_returns_410(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        capture_id = await _seed_capture(
            factory, tmp_path / "uploads", item_count=2
        )
        for seq in range(2):
            (tmp_path / "uploads" / "slices" / f"x-{seq:02d}.png").unlink()
        response = await client.post(f"/api/captures/{capture_id}/extract")

    assert response.status_code == 410
    assert gateway.calls == []
    assert await _row_count(factory) == 0


@pytest.mark.integration
async def test_provider_and_config_failures_use_distinct_status_codes(
    tmp_path, monkeypatch
) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    gateway.default_error = RuntimeError("upstream down")
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        first_id = await _seed_capture(factory, tmp_path / "uploads", item_count=2)
        first = await client.post(f"/api/captures/{first_id}/extract")

        gateway.default_error = ProviderConfigError("缺少 WENGU_DOUBAO_API_KEY")
        second_id = await _seed_capture(factory, tmp_path / "uploads", item_count=2)
        second = await client.post(f"/api/captures/{second_id}/extract")

    assert first.status_code == 502
    assert second.status_code == 503
    assert await _row_count(factory) == 0


@pytest.mark.integration
async def test_force_reslice_cascades_previous_extractions(
    tmp_path, monkeypatch
) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGateway()
    async with _make_client(factory, tmp_path, monkeypatch, gateway)[0] as client:
        upload = await client.post(
            "/api/captures",
            files={
                "file": (
                    "two_page_spread.png",
                    (FIXTURES / "two_page_spread.png").read_bytes(),
                    "image/png",
                )
            },
        )
        capture_id = upload.json()["capture_id"]
        sliced = await client.post(f"/api/captures/{capture_id}/slice")
        extracted = await client.post(f"/api/captures/{capture_id}/extract")
        rows_after_extract = await _row_count(factory)
        again = await client.post(
            f"/api/captures/{capture_id}/slice", params={"force": "true"}
        )
        after = await client.get(f"/api/captures/{capture_id}/extractions")

    assert sliced.status_code == 200
    assert extracted.json()["extracted_count"] == 10
    assert rows_after_extract == 10
    assert again.status_code == 200
    assert await _row_count(factory) == 0  # 旧 item 被删，提取级联清理
    assert after.json()["results"] == []


@pytest.mark.integration
async def test_unknown_capture_returns_404(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    async with _make_client(factory, tmp_path, monkeypatch, FakeGateway())[0] as client:
        post = await client.post("/api/captures/999/extract")
        get = await client.get("/api/captures/999/extractions")

    assert post.status_code == 404
    assert get.status_code == 404
