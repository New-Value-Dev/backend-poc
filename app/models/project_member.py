from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"
PROJECT_MEMBER_ROLES = (ROLE_OWNER, ROLE_MEMBER)

# 초대 수락 흐름 — pending 은 아직 접근 권한이 없는 "초대 대기", active 만 실제 멤버로 취급한다.
# 거절은 행을 지우지 않고 rejected 로 남겨 owner 가 "거절됨"을 볼 수 있게 하고,
# 재초대하면 다시 pending 으로 되돌린다.
MEMBER_STATUS_PENDING = "pending"
MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_REJECTED = "rejected"
PROJECT_MEMBER_STATUSES = (
    MEMBER_STATUS_PENDING,
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_REJECTED,
)


class ProjectMember(CreatedAtMixin, Base):
    """invite 프로젝트의 멤버 목록. public 프로젝트는 조회에 쓰이지 않는다"""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_MEMBER)
    # 기존 행(마이그레이션 이전에 초대된 멤버)은 server_default 로 active 가 된다.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MEMBER_STATUS_ACTIVE,
        server_default=MEMBER_STATUS_ACTIVE,
    )
    invited_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # 초대에 응답(수락/거절)한 시각 — pending 이면 None
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
