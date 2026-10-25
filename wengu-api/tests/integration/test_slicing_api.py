"""P1-3b 切片集成测试：真 RapidOCR 跑 fixture，验证 DoD 双页切成清晰单题。

DoD（TICKETS P1-3b）：双页平铺照片切成清晰单题；无锚点拒绝切分（不瞎切）；
重切幂等。fixture 为提交进仓库的合成图（tests/fixtures/），容器无需 CJK 字体。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import PhotoCapture, PhotoCaptureItem
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
FIXTURES = API_DIR / "tests" / "fixtures"
TRUTH = json.loads((FIXTURES / "two_page_spread.truth.json").read_text(encoding="utf-8"))


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "slicing.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_client(tmp_path: Path, factory: async_sessionmaker, monkeypatch) -> AsyncClient:
    uploads_dir = tmp_path / "uploads"
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    monkeypatch.setattr(
        "app.api.captures.get_settings",
        lambda: SimpleNamespace(uploads_dir=uploads_dir),
    )
    app.dependency_overrides[get_session] = override_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _upload(client: AsyncClient, path: Path) -> int:
    response = await client.post(
        "/api/captures",
        files={"file": (path.name, path.read_bytes(), "image/png")},
    )
    assert response.status_code == 201
    return response.json()["capture_id"]


@pytest.mark.integration
async def test_two_page_spread_slices_into_single_questions(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        capture_id = await _upload(client, FIXTURES / "two_page_spread.png")
        response = await client.post(f"/api/captures/{capture_id}/slice")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sliced"
    assert not body["already_sliced"]
    assert body["item_count"] == TRUTH["min_slices"] == 10
    assert body["column_split_x"] is not None  # 检出双页书缝
    assert body["header_line_count"] == 2  # 两栏页眉各一行
    labels = [item["anchor_label"] for item in body["items"]]
    assert labels[4] is None  # 间隙切出的"答："组无题号
    assert sum(1 for x in labels if x is not None) >= 8  # 其余组锚点命中
    assert [item["seq"] for item in body["items"]] == list(range(10))

    canvas_w, canvas_h = TRUTH["canvas"]
    uploads = tmp_path / "uploads"
    for item in body["items"]:
        x1, y1, x2, y2 = item["bbox"]
        assert 0 <= x1 < x2 <= canvas_w and 0 <= y1 < y2 <= canvas_h
        crop = uploads / item["stored_path"]
        assert crop.exists() and crop.stat().st_size > 0
        with Image.open(crop) as im:
            assert im.format == "PNG"
            assert im.size == (x2 - x1, y2 - y1)  # 清晰单题：裁剪尺寸与 bbox 一致

    async with factory() as session:
        rows = (
            await session.execute(
                select(func.count()).select_from(PhotoCaptureItem)
            )
        ).scalar_one()
        assert rows == 10
        capture = (
            await session.execute(
                select(PhotoCapture).where(PhotoCapture.id == capture_id)
            )
        ).scalar_one()
        assert capture.status == "sliced"


@pytest.mark.integration
async def test_reslice_is_idempotent_and_force_redoes(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        capture_id = await _upload(client, FIXTURES / "two_page_spread.png")
        first = (await client.post(f"/api/captures/{capture_id}/slice")).json()
        again = (await client.post(f"/api/captures/{capture_id}/slice")).json()
        forced = (
            await client.post(
                f"/api/captures/{capture_id}/slice", params={"force": "true"}
            )
        ).json()

    assert again["already_sliced"] is True
    assert again["item_count"] == first["item_count"]
    assert again["items"] == first["items"]
    assert forced["already_sliced"] is False
    assert forced["item_count"] == first["item_count"]

    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(PhotoCaptureItem))
        ).scalar_one() == 10  # force 先删后插，不叠加

    uploads = tmp_path / "uploads"
    crops = [p for p in uploads.rglob("slices/**/*.png")]
    assert len(crops) == 10  # 同路径覆盖，无孤儿文件


@pytest.mark.integration
async def test_force_reslice_cleans_stale_crops_when_count_shrinks(
    tmp_path, monkeypatch
) -> None:
    """模拟上次切得更多：新切块数变少时旧序号裁图必须清掉，不留磁盘孤儿。"""
    factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        capture_id = await _upload(client, FIXTURES / "two_page_spread.png")
        first = (await client.post(f"/api/captures/{capture_id}/slice")).json()
        prefix = Path(first["items"][0]["stored_path"]).stem.rsplit("-", 1)[0]
        stale_rel = f"slices/2026/10/{prefix}-99.png"
        stale_file = tmp_path / "uploads" / stale_rel
        stale_file.parent.mkdir(parents=True, exist_ok=True)
        stale_file.write_bytes(b"stale")

        async with factory() as session, session.begin():
            session.add(
                PhotoCaptureItem(
                    photo_capture_id=capture_id,
                    seq=99,
                    stored_path=stale_rel,
                    bbox_json=json.dumps([0, 0, 10, 10]),
                    anchor_label=None,
                    created_at=datetime.now(UTC),
                )
            )
        forced = (
            await client.post(
                f"/api/captures/{capture_id}/slice", params={"force": "true"}
            )
        ).json()

    assert forced["item_count"] == 10
    assert not stale_file.exists()
    assert len(list((tmp_path / "uploads").rglob("slices/**/*.png"))) == 10


@pytest.mark.integration
async def test_force_reslice_failure_keeps_previous_slices(tmp_path, monkeypatch) -> None:
    """force 重切失败（OCR 无行）不应把已成功切片的 capture 打成 slice_failed。"""
    factory = _migrated(tmp_path)

    class _EmptyEngine:
        def detect_lines(self, _path):
            return []

    async with _make_client(tmp_path, factory, monkeypatch) as client:
        capture_id = await _upload(client, FIXTURES / "two_page_spread.png")
        await client.post(f"/api/captures/{capture_id}/slice")
        monkeypatch.setattr(
            "app.api.captures.get_ocr_engine", lambda: _EmptyEngine()
        )
        failed = await client.post(
            f"/api/captures/{capture_id}/slice", params={"force": "true"}
        )
        listed = await client.get(f"/api/captures/{capture_id}/items")
        capture = await client.get(f"/api/captures/{capture_id}")

    assert failed.status_code == 422
    assert "未检测到" in failed.json()["detail"]
    assert capture.json()["status"] == "sliced"
    assert listed.json()["item_count"] == 10


@pytest.mark.integration
async def test_no_anchor_page_rejected_without_blind_slicing(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        capture_id = await _upload(client, FIXTURES / "no_anchor_page.png")
        response = await client.post(f"/api/captures/{capture_id}/slice")
        items = await client.get(f"/api/captures/{capture_id}/items")

    assert response.status_code == 422
    assert "不瞎切" in response.json()["detail"]
    assert items.json()["item_count"] == 0
    assert items.json()["already_sliced"] is False

    async with factory() as session:
        capture = (
            await session.execute(
                select(PhotoCapture).where(PhotoCapture.id == capture_id)
            )
        ).scalar_one()
        assert capture.status == "slice_failed"
        assert (
            await session.execute(select(func.count()).select_from(PhotoCaptureItem))
        ).scalar_one() == 0


@pytest.mark.integration
async def test_items_endpoint_and_missing_capture(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        capture_id = await _upload(client, FIXTURES / "two_page_spread.png")
        await client.post(f"/api/captures/{capture_id}/slice")
        listed = await client.get(f"/api/captures/{capture_id}/items")
        missing = await client.get("/api/captures/999/items")
        missing_slice = await client.post("/api/captures/999/slice")

    assert listed.status_code == 200
    body = listed.json()
    assert body["item_count"] == 10
    assert body["status"] == "sliced"
    assert body["already_sliced"] is True
    assert body["items"][0]["stored_path"].startswith("slices/")
    assert missing.status_code == 404
    assert missing_slice.status_code == 404


@pytest.mark.integration
async def test_slicing_never_calls_vlm(tmp_path, monkeypatch) -> None:
    """切题链路零 VLM 调用（OCR 是本地 onnxruntime，引擎可换）。"""

    from app.services import ai_gateway

    def _boom(*args, **kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError("切题链路不允许触发 VLM")

    monkeypatch.setattr(ai_gateway.AiGateway, "extract_problem", _boom)
    monkeypatch.setattr(ai_gateway.AiGateway, "grade", _boom)
    monkeypatch.setattr(ai_gateway.AiGateway, "solve_explain", _boom)

    factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        capture_id = await _upload(client, FIXTURES / "two_page_spread.png")
        response = await client.post(f"/api/captures/{capture_id}/slice")
    assert response.status_code == 200
    assert response.json()["item_count"] == 10
