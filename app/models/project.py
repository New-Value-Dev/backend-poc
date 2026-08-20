from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.folder import Folder
    from app.models.project_member import ProjectMember

VISIBILITY_PUBLIC = "public"
VISIBILITY_INVITE = "invite"
VISIBILITY_PRIVATE = "private"
PROJECT_VISIBILITIES = (VISIBILITY_PUBLIC, VISIBILITY_INVITE, VISIBILITY_PRIVATE)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(255))
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VISIBILITY_PUBLIC, server_default=VISIBILITY_PUBLIC
    )

    folders: Mapped[list[Folder]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
