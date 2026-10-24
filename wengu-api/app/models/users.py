"""user_role：单用户两角色 + 本地 PIN（scrypt 哈希，P2-4 解锁家长视图用）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRole(Base):
    __tablename__ = "user_role"

    role: Mapped[str] = mapped_column(Text, primary_key=True)  # child | parent
    pin_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
