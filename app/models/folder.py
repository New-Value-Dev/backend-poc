from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.project import Project


class Folder(CreatedAtMixin, Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("folders.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    project: Mapped[Project] = relationship(back_populates="folders")
    parent: Mapped[Folder | None] = relationship(
        remote_side="Folder.id", back_populates="children"
    )
    children: Mapped[list[Folder]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    documents: Mapped[list[Document]] = relationship(back_populates="folder")
