from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project


class QuizBook(TimestampMixin, Base):
    """문제집. 문제은행에서 문항을 골라 구성한 응시 단위"""

    __tablename__ = "quiz_books"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # 표시/스코프용 참고 정보일 뿐 — 실제 소속 문항은 quiz_book_questions
    source_document_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    passing_score: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    shuffle_options: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_retake: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reveal_answers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    project: Mapped[Project] = relationship()
