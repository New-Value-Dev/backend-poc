from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin

QUIZ_GEN_STATUS_RUNNING = "RUNNING"
QUIZ_GEN_STATUS_COMPLETED = "COMPLETED"
QUIZ_GEN_STATUS_FAILED = "FAILED"
QUIZ_GEN_STATUSES = (
    QUIZ_GEN_STATUS_RUNNING,
    QUIZ_GEN_STATUS_COMPLETED,
    QUIZ_GEN_STATUS_FAILED,
)


class QuizGenerationJob(TimestampMixin, Base):
    """AI 문제 생성 작업 1건(202 + 폴링).

    `ai_analysis_results` 를 재사용하지 않는 이유: 그 테이블은 document_id/document_version_id
    가 둘 다 NOT NULL 인데, 퀴즈 생성은 여러 문서를 한 번에 걸칠 수 있다.
    """

    __tablename__ = "quiz_generation_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 문제집이 지워져도 생성 이력 자체는 남겨야 하므로 SET NULL
    quiz_book_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quiz_books.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=QUIZ_GEN_STATUS_RUNNING,
        server_default=QUIZ_GEN_STATUS_RUNNING,
    )
    # 요청 스냅샷(document_ids/types/difficulty/...) — 나중에 "무슨 조건으로 만든 문제였나"를 본다
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 배치마다 커밋하며 올라간다 → 폴링 중 진행률로 쓸 수 있다
    created_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    question_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    provider: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
