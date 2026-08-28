from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.user import User


class QuizBookAssignee(CreatedAtMixin, Base):
    """이 문제집을 풀어야 할 사람으로 지정된 사용자"""

    __tablename__ = "quiz_book_assignees"
    __table_args__ = (
        UniqueConstraint("quiz_book_id", "user_id", name="uq_quiz_book_assignees_book_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    quiz_book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_books.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    assigned_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # 마감 임박 리마인더 중복 발송 방지 — 보낸 적 있으면 채워진다
    due_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(foreign_keys=[user_id])
