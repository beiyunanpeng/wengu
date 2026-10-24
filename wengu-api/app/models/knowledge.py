"""知识点：knowledge_seed（粗粒度预置）+ concepts（细粒度受控生长）+ 先修边。

seed 以 JSON 文件为分发真源（AGENTS §2），此表是运行时装载副本与挂载锚点。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KnowledgeSeed(Base):
    __tablename__ = "knowledge_seed"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # 如 cnm_*
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[str | None] = mapped_column(Text, nullable=True)
    semester: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mastery_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnostic_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    standards: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    unaudited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    blind_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("knowledge_seed.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # ai | student | parent
    status: Mapped[str] = mapped_column(Text, nullable=False, default="suggested")
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (UniqueConstraint("name", "category_id", name="uq_concepts_name_category"),)


class ConceptAlias(Base):
    __tablename__ = "concept_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("concept_id", "alias", name="uq_concept_aliases_concept_alias"),
    )


class PrerequisiteEdge(Base):
    __tablename__ = "prerequisite_edges"

    parent_id: Mapped[str] = mapped_column(ForeignKey("knowledge_seed.id"), primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("knowledge_seed.id"), primary_key=True)
    edge_type: Mapped[str] = mapped_column(Text, nullable=False)  # hard | soft
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
