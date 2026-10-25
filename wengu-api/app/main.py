"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.captures import router as captures_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.seed import router as seed_router
from app.core.database import get_session_factory
from app.seed.loader import load_seed

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动时装载 seed（幂等；JSON 缺失则空 seed 起步，不阻塞服务）。"""

    try:
        async with get_session_factory()() as session:
            await load_seed(session)
    except Exception:
        logger.exception("seed 装载失败，以空 seed 继续（检查 seeds/data/*.json）")
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="wengu · 温故", version=__version__, lifespan=_lifespan)
    application.include_router(health_router)
    application.include_router(seed_router)
    application.include_router(captures_router)
    application.include_router(imports_router)
    return application


app = create_app()
