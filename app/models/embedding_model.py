from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.chunk_embedding import ChunkEmbedding


class EmbeddingModel(CreatedAtMixin, Base):
    """등록된 로컬 Embedding 모델 정보"""

    __tablename__ = "embedding_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(50))
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    model_path: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="TEST")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    embeddings: Mapped[list[ChunkEmbedding]] = relationship(back_populates="embedding_model")
