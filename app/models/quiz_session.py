from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin

MODE_STUDY = "study"
MODE_EXAM = "exam"
QUIZ_SESSION_MODES = (MODE_STUDY, MODE_EXAM)

SESSION_STATUS_IN_PROGRESS = "IN_PROGRESS"
SESSION_STATUS_SUBMITTED = "SUBMITTED"
QUIZ_SESSION_STATUSES = (SESSION_STATUS_IN_PROGRESS, SESSION_STATUS_SUBMITTED)


class QuizSession(TimestampMixin, Base):
    """한 사용자가 한 문제집을 응시한 기록(진행 중 ~ 제출 완료)."""

    __tablename__ = "quiz_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    quiz_book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_books.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default=MODE_EXAM)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SESSION_STATUS_IN_PROGRESS,
        server_default=SESSION_STATUS_IN_PROGRESS,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)
    correct_count: Mapped[int | None] = mapped_column(Integer)
    total_count: Mapped[int | None] = mapped_column(Integer)
