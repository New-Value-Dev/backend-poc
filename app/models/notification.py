from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import CreatedAtMixin


class Notification(CreatedAtMixin, Base):
    """사용자별 인앱 알림(알림함)"""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 알림 종류 (notification_service.NotificationType)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    # 클릭 시 이동할 프론트 경로 (예: /projects/12)
    url: Mapped[str | None] = mapped_column(String(500))
    # 종류별 부가 정보 (project_id, document_id, analysis_id ...)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
