from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_section import DocumentSection


class DocumentVersion(CreatedAtMixin, Base):
    """실제 업로드된 파일 버전."""

    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(String(128))
    processing_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="UPLOADED"
    )
    parser_version: Mapped[str | None] = mapped_column(String(50))

    document: Mapped[Document] = relationship(
        back_populates="versions", foreign_keys=[document_id]
    )
    sections: Mapped[list[DocumentSection]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )
