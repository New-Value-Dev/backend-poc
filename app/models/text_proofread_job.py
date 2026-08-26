from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class TextProofreadJob(TimestampMixin, Base):
    """문서 없이 원문 텍스트만 검사하는 `/text/proofread` job"""

    __tablename__ = "text_proofread_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # RUNNING / COMPLETED / FAILED
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RUNNING")
    provider: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {"findings": [...]}
    error: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship()
