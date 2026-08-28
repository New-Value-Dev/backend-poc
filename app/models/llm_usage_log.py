from __future__ import annotations

from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

STATUS_SUCCESS = "success"
STATUS_FAIL = "fail"


class LLMUsageLog(CreatedAtMixin, Base):
    """OpenAI 호출 1건의 토큰 사용량 + 성공/실패 기록"""

    __tablename__ = "llm_usage_logs"
    __table_args__ = (
        Index("ix_llm_usage_logs_created_at", "created_at"),
        Index("ix_llm_usage_logs_feature_created_at", "feature", "created_at"),
        Index("ix_llm_usage_logs_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # proofread | proofread_batch | rag_rewrite | rag_answer | rag_answer_stream |
    # quiz_generate | quiz_grade_essay | quiz_grade_short_answer
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL")
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
