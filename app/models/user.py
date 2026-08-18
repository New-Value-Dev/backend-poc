from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    """로그인 사용자 OAuth provider + provider 내 고유 식별자로 매핑"""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("provider", "provider_sub", name="uq_users_provider_sub"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
