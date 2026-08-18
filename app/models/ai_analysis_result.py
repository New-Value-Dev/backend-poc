from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_version import DocumentVersion


class AiAnalysisResult(TimestampMixin, Base):
    """모든 AI 모듈의 결과 적재 테이블"""

    __tablename__ = "ai_analysis_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # "proofread" / "classify" / "validate" / "related" ...
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # RUNNING / COMPLETED / FAILED
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="COMPLETED")
    # 결과를 만든 LLM provider 식별자
    provider: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(255))

    document: Mapped[Document] = relationship()
    document_version: Mapped[DocumentVersion] = relationship()
