from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models.project import Project
from app.models.project_member import (
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_PENDING,
    ProjectMember,
)
from app.models.user import User


class ProjectMemberRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, project_id: int, user_id: int) -> ProjectMember | None:
        """상태와 무관하게 행을 가져온다"""
        return self.db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )

    def get_active(self, project_id: int, user_id: int) -> ProjectMember | None:
        """실제로 접근 권한이 있는 멤버만"""
        return self.db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.status == MEMBER_STATUS_ACTIVE,
            )
        )

    def list_with_user(self, project_id: int) -> list[tuple[ProjectMember, User]]:
        """멤버 목록"""
        stmt = (
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.created_at)
        )
        return [(row[0], row[1]) for row in self.db.execute(stmt)]

    def list_user_ids(
        self, project_id: int, *, statuses: Sequence[str] | None = None
    ) -> set[int]:
        """이미 초대/가입한 사람"""
        stmt = select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
        if statuses is not None:
            stmt = stmt.where(ProjectMember.status.in_(statuses))
        return set(self.db.scalars(stmt))

    def list_pending_for_user(
        self, user_id: int
    ) -> list[tuple[ProjectMember, Project, User | None]]:
        """내가 받은 수락 대기 초대 목록"""
        inviter = aliased(User)
        stmt = (
            select(ProjectMember, Project, inviter)
            .join(Project, Project.id == ProjectMember.project_id)
            .outerjoin(inviter, inviter.id == ProjectMember.invited_by)
            .where(
                ProjectMember.user_id == user_id,
                ProjectMember.status == MEMBER_STATUS_PENDING,
            )
            .order_by(ProjectMember.created_at.desc())
        )
        return [(row[0], row[1], row[2]) for row in self.db.execute(stmt)]

    def add(
        self,
        *,
        project_id: int,
        user_id: int,
        role: str,
        invited_by: int | None,
        status: str = MEMBER_STATUS_ACTIVE,
    ) -> ProjectMember:
        member = ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            status=status,
        )
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return member

    def mark_invited(
        self, member: ProjectMember, *, invited_by: int | None
    ) -> ProjectMember:
        """거절했던 사람을 다시 초대할 때"""
        member.status = MEMBER_STATUS_PENDING
        member.invited_by = invited_by
        member.responded_at = None
        self.db.commit()
        self.db.refresh(member)
        return member

    def set_status(self, member: ProjectMember, status: str) -> ProjectMember:
        member.status = status
        member.responded_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(member)
        return member

    def remove(self, member: ProjectMember) -> None:
        self.db.delete(member)
        self.db.commit()
