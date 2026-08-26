from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import CreatedAtMixin


class QuizBookQuestion(CreatedAtMixin, Base):
    """QuizBook + QuizQuestion 연결"""

    __tablename__ = "quiz_book_questions"
    __table_args__ = (
        UniqueConstraint(
            "quiz_book_id", "quiz_question_id", name="uq_quiz_book_questions_book_question"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    quiz_book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_books.id", ondelete="CASCADE"), nullable=False
    )
    quiz_question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False
    )
    # 문제집 내 표시 순서(밀집 정수) — 재정렬 시 전체를 다시 매긴다
    order_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
