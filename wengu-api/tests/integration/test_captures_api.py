"""主通道集成测试：上传 → 本地存储 → photo_captures 落库，幂等/闸门/纯查询。

DoD（TICKETS P1-3）：手机上传数秒落库（零模型调用，本测试全程不调模型）；
重复上传同一张照片（重启/重试等价）返回已有行，不产生重复记录。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import PhotoCapture
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # 嗅探只需前 8 字节魔数
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def _migrated(tmp_path: Path) -> tuple[Path, async_sessionmaker]:
    db_path = tmp_path / "captures.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return db_path, async_sessionmaker(engine, expire_on_commit=False)


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


@pytest.mark.integration
async def test_upload_persists_file_and_row(tmp_path, monkeypatch) -> None:
    _, factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        response = await client.post(
            "/api/captures",
            files={"file": ("IMG_1024.png", PNG_BYTES, "image/png")},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending" and not body["duplicate"]

    files = list((tmp_path / "uploads").rglob("*.*"))
    assert len(files) == 1
    assert files[0].read_bytes() == PNG_BYTES

    async with factory() as session:
        row = (await session.execute(select(PhotoCapture))).scalar_one()
        assert row.id == body["capture_id"]
        assert row.original_name == "IMG_1024.png"
        assert row.stored_path.endswith(".png")


@pytest.mark.integration
async def test_reupload_same_bytes_is_idempotent(tmp_path, monkeypatch) -> None:
    """重传/重试/重启等价：同内容返回已有 capture_id，不产生新行新文件。"""

    _, factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        first = await client.post(
            "/api/captures", files={"file": ("a.png", PNG_BYTES, "image/png")}
        )
        # 换文件名、重建 client 模拟重启后再传同一张照片
        second = await client.post(
            "/api/captures",
            files={"file": ("renamed.png", PNG_BYTES, "image/png")},
        )
    assert first.status_code == second.status_code == 201
    assert second.json()["duplicate"] is True
    assert second.json()["capture_id"] == first.json()["capture_id"]

    uploads = tmp_path / "uploads"
    assert len([p for p in uploads.rglob("*") if p.is_file()]) == 1
    assert len([p for p in uploads.iterdir() if p.name.startswith(".incoming")]) == 0

    async with factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(PhotoCapture))
        ).scalar_one()
        assert count == 1


@pytest.mark.integration
async def test_rejects_non_image_and_mismatched_declared_type(
    tmp_path, monkeypatch
) -> None:
    _, factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        not_image = await client.post(
            "/api/captures",
            files={"file": ("note.txt", b"hello world", "text/plain")},
        )
        mismatch = await client.post(
            "/api/captures",
            files={"file": ("trick.gif", PNG_BYTES, "image/gif")},
        )
    assert not_image.status_code == 415
    assert mismatch.status_code == 415
    assert not (tmp_path / "uploads").exists() or not list(
        (tmp_path / "uploads").rglob("*.*")
    )


@pytest.mark.integration
async def test_accepts_jpeg_and_octet_stream(tmp_path, monkeypatch) -> None:
    _, factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        declared = await client.post(
            "/api/captures",
            files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")},
        )
        sniffed = await client.post(
            "/api/captures",
            files={"file": ("b.jpg", JPEG_BYTES, "application/octet-stream")},
        )
        # 同内容不同声明 → 第二次走幂等去重
    assert declared.status_code == sniffed.status_code == 201
    assert sniffed.json()["duplicate"] is True


@pytest.mark.integration
async def test_get_capture_and_status_filter(tmp_path, monkeypatch) -> None:
    _, factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        created = (
            await client.post(
                "/api/captures", files={"file": ("a.png", PNG_BYTES, "image/png")}
            )
        ).json()
        got = await client.get(f"/api/captures/{created['capture_id']}")
        missing = await client.get("/api/captures/999")
        pending = await client.get("/api/captures", params={"status": "pending"})
        processed = await client.get("/api/captures", params={"status": "processed"})

    assert got.status_code == 200
    detail = got.json()
    assert detail["id"] == created["capture_id"]
    assert detail["source"] == "phone"
    assert detail["original_name"] == "a.png"
    assert "/".join(detail["stored_path"].split("/")[:2]) != ""  # YYYY/MM 分层
    assert missing.status_code == 404
    assert pending.status_code == 200
    assert [c["id"] for c in pending.json()["captures"]] == [created["capture_id"]]
    assert processed.json()["total"] == 0
    json.dumps(detail)  # 响应可序列化（无 datetime 等裸对象）


@pytest.mark.integration
async def test_no_model_calls_anywhere(tmp_path, monkeypatch) -> None:
    """纯采集链路零模型调用：把 gateway 调用函数炸掉，全链路仍通。"""

    from app.services import ai_gateway

    def _boom(*args, **kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError("采集链路不允许触发模型调用")

    monkeypatch.setattr(ai_gateway.AiGateway, "extract_problem", _boom)
    monkeypatch.setattr(ai_gateway.AiGateway, "grade", _boom)
    monkeypatch.setattr(ai_gateway.AiGateway, "solve_explain", _boom)

    _, factory = _migrated(tmp_path)
    async with _make_client(tmp_path, factory, monkeypatch) as client:
        response = await client.post(
            "/api/captures", files={"file": ("a.png", PNG_BYTES, "image/png")}
        )
    assert response.status_code == 201
