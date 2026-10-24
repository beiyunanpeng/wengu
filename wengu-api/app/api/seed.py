"""GET /api/seed/summary：seed 装载状态只读查询（纯查询，绝不触发模型调用）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models import KnowledgeSeed, PrerequisiteEdge
from app.seed.loader import load_mappings

router = APIRouter(tags=["seed"])


class SubjectSummary(BaseModel):
    topics: int
    unaudited: int
    blind_verified: int


class MappingInfo(BaseModel):
    edition: str
    label: str
    status: str
    entry_count: int


class SeedSummary(BaseModel):
    topics_total: int
    edges_total: int
    subjects: dict[str, SubjectSummary]
    mappings: list[MappingInfo]


@router.get("/api/seed/summary", response_model=SeedSummary)
async def seed_summary(session: AsyncSession = Depends(get_session)) -> SeedSummary:
    rows = (
        await session.execute(
            select(
                KnowledgeSeed.subject,
                func.count(),
                # Boolean 列直接 sum 会被 SQLAlchemy 结果处理器转成 True/False，必须显式转 Integer
                func.sum(func.cast(KnowledgeSeed.unaudited, Integer)),
                func.sum(func.cast(KnowledgeSeed.blind_verified, Integer)),
            ).group_by(KnowledgeSeed.subject)
        )
    ).all()
    subjects = {
        subject: SubjectSummary(
            topics=count, unaudited=unaudited or 0, blind_verified=verified or 0
        )
        for subject, count, unaudited, verified in rows
    }
    edges_total = (
        await session.execute(select(func.count()).select_from(PrerequisiteEdge))
    ).scalar_one()
    mappings = [
        MappingInfo(**m) for m in load_mappings(get_settings().seeds_dir / "mappings")
    ]
    return SeedSummary(
        topics_total=sum(s.topics for s in subjects.values()),
        edges_total=edges_total,
        subjects=subjects,
        mappings=mappings,
    )
