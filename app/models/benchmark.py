"""EmbeddingLab 벤치마크 스키마"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.embedding_model import EmbeddingModel


class BenchmarkDataset(CreatedAtMixin, Base):
    __tablename__ = "benchmark_datasets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL")
    )
    created_by: Mapped[str | None] = mapped_column(String(64))

    questions: Mapped[list["BenchmarkQuestion"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class BenchmarkQuestion(CreatedAtMixin, Base):
    """정답(ground_truth)은 section_id FK가 아니라 스니펫으로 저장한다.

    재파싱 시 document_sections는 delete+insert로 통째로 교체되므로(_persist_sections)
    FK는 한 번만 재파싱해도 깨진다. 대신 "검색된 청크 content에 스니펫이 포함되는지"로
    채점해 청킹 설정이 바뀌어도 재사용 가능한 정답 기준으로 삼는다.
    """

    __tablename__ = "benchmark_questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("benchmark_datasets.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    # [{"document_id": int, "expected_snippet": str, "page_start": int|None}, ...]
    ground_truth: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    dataset: Mapped[BenchmarkDataset] = relationship(back_populates="questions")


class BenchmarkRun(CreatedAtMixin, Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("benchmark_datasets.id", ondelete="CASCADE"), nullable=False
    )
    # ChunkingParams 스냅샷: {strategy, max_chars, overlap, sentence_window, breakpoint_percentile}
    chunking_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rag_top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    rag_min_score: Mapped[float] = mapped_column(Float, nullable=False)
    # 재현성을 위해 이 run이 어떤 document_version들을 대상으로 청킹했는지 기록
    target_document_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    created_by: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list["BenchmarkResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class BenchmarkResult(CreatedAtMixin, Base):
    __tablename__ = "benchmark_results"
    __table_args__ = (
        UniqueConstraint("run_id", "embedding_model_id", name="uq_benchmark_results_run_model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False
    )
    embedding_model_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("embedding_models.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    recall_at_1: Mapped[float | None] = mapped_column(Float)
    recall_at_3: Mapped[float | None] = mapped_column(Float)
    recall_at_5: Mapped[float | None] = mapped_column(Float)
    mrr: Mapped[float | None] = mapped_column(Float)
    ndcg: Mapped[float | None] = mapped_column(Float)
    avg_query_latency_ms: Mapped[float | None] = mapped_column(Float)
    embed_throughput_chunks_per_sec: Mapped[float | None] = mapped_column(Float)
    model_load_time_ms: Mapped[float | None] = mapped_column(Float)
    ram_mb: Mapped[float | None] = mapped_column(Float)
    # DESIGN.md §9 가중치(정확도60·성능15·latency10·RAM10·운영편의성5) 적용한 합성 점수
    score: Mapped[float | None] = mapped_column(Float)
    question_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[BenchmarkRun] = relationship(back_populates="results")
    embedding_model: Mapped["EmbeddingModel"] = relationship()
