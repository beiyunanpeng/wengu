"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.attempts import router as attempts_router
from app.api.captures import router as captures_router
from app.api.concepts import router as concepts_router
from app.api.explanations import router as explanations_router
from app.api.extractions import router as extractions_router
from app.api.gradings import router as gradings_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.mistakes import router as mistakes_router
from app.api.practice import router as practice_router
from app.api.problem_bank import router as problem_bank_router
from app.api.reviews import router as reviews_router
from app.api.seed import router as seed_router
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.seed.loader import load_seed
from app.services.inbox import inbox_watcher

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动时装载 seed（幂等；JSON 缺失则空 seed 起步，不阻塞服务）。

    同时拉起 inbox 监听目录扫描（v2.5 主入本通道，P1-3d）——
    未处理文件始终留在监听目录，停机不丢、重启补扫。
    """

    try:
        async with get_session_factory()() as session:
            await load_seed(session)
    except Exception:
        logger.exception("seed 装载失败，以空 seed 继续（检查 seeds/data/*.json）")

    settings = get_settings()
    stop_event = asyncio.Event()
    watcher_task: asyncio.Task[None] | None = None
    try:
        settings.inbox_path.mkdir(parents=True, exist_ok=True)
        watcher_task = asyncio.create_task(
            inbox_watcher(get_session_factory(), settings.inbox_path, stop_event)
        )
    except OSError:
        logger.exception("inbox 目录不可用，跳过目录监听（仅保留 HTTP 导入通道）")
    yield
    stop_event.set()
    if watcher_task is not None:
        watcher_task.cancel()
        await asyncio.gather(watcher_task, return_exceptions=True)


def create_app() -> FastAPI:
    # WENGU_LOG_LEVEL 此前只在配置里定义、从未生效；后台 watcher 依赖日志可观测
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    application = FastAPI(title="wengu · 温故", version=__version__, lifespan=_lifespan)
    application.include_router(health_router)
    application.include_router(seed_router)
    application.include_router(captures_router)
    application.include_router(extractions_router)
    application.include_router(gradings_router)
    application.include_router(mistakes_router)
    application.include_router(concepts_router)
    application.include_router(practice_router)
    application.include_router(attempts_router)
    application.include_router(problem_bank_router)
    application.include_router(reviews_router)
    application.include_router(imports_router)
    application.include_router(explanations_router)
    return application


app = create_app()
