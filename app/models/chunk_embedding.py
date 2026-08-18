from __future__ import annotations

from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.document_chunk import DocumentChunk
    from app.models.embedding_model import EmbeddingModel

# 초기 후보 3종(BGE-M3 / KURE-v1 / Qwen3)을 1024 차원으로 통일한다.
EMBEDDING_DIM = 1024


class ChunkEmbedding(CreatedAtMixin, Base):
    """Chunk 1 : N 모델 벡터. 같은 Chunk 에 여러 모델 벡터가 공존할 수 있다."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_model_id", name="uq_chunk_embeddings_chunk_model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chunk_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False
    )
    embedding_model_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("embedding_models.id", ondelete="CASCADE"), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    chunk: Mapped[DocumentChunk] = relationship(back_populates="embeddings")
    embedding_model: Mapped[EmbeddingModel] = relationship(back_populates="embeddings")
