from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.document_version import DocumentVersion


class DocumentSection(CreatedAtMixin, Base):
    """Parser 결과의 문서 구조(제목/문단/조항 등)."""

    __tablename__ = "document_sections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    parent_section_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("document_sections.id", ondelete="CASCADE")
    )
    title: Mapped[str | None] = mapped_column(String(1000))
    section_type: Mapped[str | None] = mapped_column(String(50))
    # heading 깊이(1~9, 작을수록 상위) 본문/표 등 비-heading 은 100(BODY_LEVEL)
    level: Mapped[int | None] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str | None] = mapped_column(Text)
    # 파서 부가정보: bbox(페이지 좌표), heading level, ocr 여부/신뢰도 등
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="sections")
    parent: Mapped[DocumentSection | None] = relationship(
        remote_side="DocumentSection.id", back_populates="children"
    )
    children: Mapped[list[DocumentSection]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
