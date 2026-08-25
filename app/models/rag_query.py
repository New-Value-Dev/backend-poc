from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.embedding_model import EmbeddingModel


class RagQuery(CreatedAtMixin, Base):
    """RAG 질의 이력. 질문/답변/출처가 여러 문서·프로젝트에 걸칠 수 있어
    document_id 를 강제하는 ai_analysis_results 와는 별도 테이블로 둔다."""

    __tablename__ = "rag_queries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    project_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    folder_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # 답변을 만든 LLM provider 식별자
    provider: Mapped[str | None] = mapped_column(String(100))
    embedding_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("embedding_models.id", ondelete="SET NULL")
    )
    created_by: Mapped[str | None] = mapped_column(String(255))

    embedding_model: Mapped[EmbeddingModel | None] = relationship()
