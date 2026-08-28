from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.project import Project

QUESTION_TYPE_SINGLE_CHOICE = "SINGLE_CHOICE"
QUESTION_TYPE_TRUE_FALSE = "TRUE_FALSE"
QUESTION_TYPE_SHORT_ANSWER = "SHORT_ANSWER"
QUESTION_TYPE_ESSAY = "ESSAY"
QUIZ_QUESTION_TYPES = (
    QUESTION_TYPE_SINGLE_CHOICE,
    QUESTION_TYPE_TRUE_FALSE,
    QUESTION_TYPE_SHORT_ANSWER,
    QUESTION_TYPE_ESSAY,
)

DIFFICULTY_EASY = "EASY"
DIFFICULTY_MEDIUM = "MEDIUM"
DIFFICULTY_HARD = "HARD"
QUIZ_DIFFICULTIES = (DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD)

GENERATION_TYPE_MANUAL = "MANUAL"
GENERATION_TYPE_AI = "AI"
GENERATION_TYPES = (GENERATION_TYPE_MANUAL, GENERATION_TYPE_AI)

REVIEW_STATUS_DRAFT = "DRAFT"
REVIEW_STATUS_REVIEWED = "REVIEWED"
REVIEW_STATUS_APPROVED = "APPROVED"
QUIZ_REVIEW_STATUSES = (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REVIEWED, REVIEW_STATUS_APPROVED)


class QuizQuestion(TimestampMixin, Base):
    """문제은행 문항 1건. 특정 문제집에 소속되지 않고 프로젝트 전체에서 공유된다."""

    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # SINGLE_CHOICE 에서만 사용
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    # SINGLE_CHOICE 는 options 의 인덱스(문자열), TRUE_FALSE 는 "O"/"X",
    # SHORT_ANSWER/ESSAY 는 정답(모범답안) 텍스트
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    # ESSAY 에서는 GPT 채점 시 채점기준으로도 재사용
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    source_location: Mapped[str | None] = mapped_column(String(500))
    generation_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default=GENERATION_TYPE_MANUAL
    )
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=REVIEW_STATUS_DRAFT, server_default=REVIEW_STATUS_DRAFT
    )

    project: Mapped[Project] = relationship()
    source_document: Mapped[Document | None] = relationship()

    @property
    def source_document_title(self) -> str | None:
        """'분야'를 태그 대신 출처 문서 단위로 보여주기 위한 편의 필드 — QuizQuestionRead 에서 노출."""
        return self.source_document.name if self.source_document else None
