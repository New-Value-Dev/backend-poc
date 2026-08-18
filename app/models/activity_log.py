from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import CreatedAtMixin


class ActivityLog(CreatedAtMixin, Base):
    """누가/언제/무엇을 했는지 남기는 감사 로그 """

    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("ix_activity_logs_created_at", "created_at"),
        Index("ix_activity_logs_project_created_at", "project_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 누가
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    # 기록 시점의 사용자 이름
    actor_label: Mapped[str | None] = mapped_column(String(255))
    # 무엇을
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # 어디서
    project_id: Mapped[int | None] = mapped_column(BigInteger)
    # 대상
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    # 기록 시점의 대상 이름
    target_label: Mapped[str | None] = mapped_column(String(500))
    # 액션별 부가 정보
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
