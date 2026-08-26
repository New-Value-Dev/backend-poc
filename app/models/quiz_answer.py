from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import CreatedAtMixin


class QuizAnswer(CreatedAtMixin, Base):
    """세션 내 문항 1개에 대한 답변. 채점에 필요한 문제 내용은 제출 시점 스냅샷으로 저장"""

    __tablename__ = "quiz_answers"
    __table_args__ = (
        UniqueConstraint("session_id", "question_id", name="uq_quiz_answers_session_question"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_sessions.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quiz_questions.id", ondelete="SET NULL")
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
