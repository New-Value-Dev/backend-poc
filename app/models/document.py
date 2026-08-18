from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.document_version import DocumentVersion
    from app.models.folder import Folder
    from app.models.project import Project


class Document(TimestampMixin, Base):
    """논리적 문서/ 실제 파일은 document_versions 로 관리"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    folder_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("folders.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(String(50))
    # 상태 컬럼은 일부러 두지 않는다 — 문서 상태 = 현재 버전의 processing_status
    current_version_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[str | None] = mapped_column(String(255))

    project: Mapped[Project] = relationship(back_populates="documents")
    folder: Mapped[Folder | None] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentVersion.document_id",
    )
