from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import CreatedAtMixin


class ChunkingConfig(CreatedAtMixin, Base):
    """운영에 적용된(또는 적용 예정인) 청킹 파라미터 스냅샷"""

    __tablename__ = "chunking_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    chunk_max_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    # structure 청킹 하한 — 같은 heading 아래 인접 본문 섹션을 이 길이까지 뭉친다(0=뭉치지 않음)
    chunk_min_chars: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300, server_default="300"
    )
    chunk_overlap_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=150)
    sentence_window: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    breakpoint_percentile: Mapped[float] = mapped_column(Float, nullable=False, default=95.0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_benchmark_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("benchmark_runs.id", ondelete="SET NULL")
    )
