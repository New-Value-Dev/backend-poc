from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.embedding_model import EmbeddingModel


class EmbeddingJob(CreatedAtMixin, Base):
    """`reembed`/`migrate` 백그라운드 작업의 진행 상황 폴링용."""

    __tablename__ = "embedding_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(20), nullable=False)  # reembed | migrate
    embedding_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("embedding_models.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    embedding_model: Mapped["EmbeddingModel | None"] = relationship()
