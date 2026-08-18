from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.chunk_embedding import ChunkEmbedding


class DocumentChunk(CreatedAtMixin, Base):
    """RAG 의 최소 검색 단위"""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("document_sections.id", ondelete="SET NULL")
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    # 예약어 metadata 와 충돌을 피하려고 속성명은 chunk_metadata, 컬럼명은 metadata 로 둔다.
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    embeddings: Mapped[list[ChunkEmbedding]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )
