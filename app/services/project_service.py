from typing import NamedTuple

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.project import VISIBILITY_INVITE, VISIBILITY_PUBLIC, Project
from app.models.project_member import (
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_PENDING,
    MEMBER_STATUS_REJECTED,
    ROLE_MEMBER,
    ROLE_OWNER,
    ProjectMember,
)
from app.models.user import User
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.project import (
    ProjectCreate,
    ProjectInvitationRead,
    ProjectMemberRead,
    ProjectUpdate,
)

ADMIN_ROLE = "admin"


class ProjectNotFoundError(Exception):
    """요청한 프로젝트가 존재하지 않을 때 발생."""

    def __init__(self, project_id: int) -> None:
        self.project_id = project_id
        super().__init__(f"Project {project_id} not found")


class ProjectForbiddenError(Exception):
    """로그인은 했지만 이 프로젝트에 대한 접근/조작 권한이 없을 때 발생."""

    def __init__(self, project_id: int) -> None:
        self.project_id = project_id
        super().__init__(f"No access to project {project_id}")


class ProjectMemberNotFoundError(Exception):
    def __init__(self, project_id: int, user_id: int) -> None:
        self.project_id = project_id
        self.user_id = user_id
        super().__init__(f"User {user_id} is not a member of project {project_id}")


class ProjectMemberAlreadyExistsError(Exception):
    def __init__(self, project_id: int, user_id: int) -> None:
        self.project_id = project_id
        self.user_id = user_id
        super().__init__(f"User {user_id} is already a member of project {project_id}")


class ProjectMemberInvitePendingError(Exception):
    """이미 수락 대기 중인 초대가 있을 때."""

    def __init__(self, project_id: int, user_id: int) -> None:
        self.project_id = project_id
        self.user_id = user_id
        super().__init__(f"User {user_id} already has a pending invite to {project_id}")


class ProjectInvitationNotFoundError(Exception):
    """수락/거절할 대기 중 초대가 없을 때(이미 응답했거나 초대받지 않았거나)."""

    def __init__(self, project_id: int, user_id: int) -> None:
        self.project_id = project_id
        self.user_id = user_id
        super().__init__(f"No pending invitation to project {project_id} for user {user_id}")


class InviteeNotFoundError(Exception):
    """초대하려는 이메일/사용자 id 로 가입된 사용자가 없을 때."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        # 하위 호환 — 기존 호출부가 .email 을 참조한다.
        self.email = identifier
        super().__init__(f"No user matching {identifier}")


class InvitationOutcome(NamedTuple):
    """수락/거절 결과 — 라우터가 알림을 보낼 대상(초대한 사람)을 알아야 해서 함께 돌려준다."""

    project: Project
    member: ProjectMember
    # 초대한 사람(없으면 owner 에게 알린다)
    notify_user_id: int | None


def _is_admin(user: User) -> bool:
    return user.role == ADMIN_ROLE


class ProjectService:
    def __init__(
        self,
        repository: ProjectRepository,
        members: ProjectMemberRepository,
        users: UserRepository,
    ) -> None:
        self.repository = repository
        self.members = members
        self.users = users

    # ── 조회 ──

    def list_projects(self, current_user: User) -> list[Project]:
        if _is_admin(current_user):
            return self.repository.list()
        return self.repository.list_accessible(current_user.id)

    def get_project(self, project_id: int) -> Project:
        project = self.repository.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    def _can_access(self, project: Project, user: User) -> bool:
        if _is_admin(user):
            return True
        if project.visibility == VISIBILITY_PUBLIC:
            return True
        if project.owner_id == user.id:
            return True
        if project.visibility == VISIBILITY_INVITE:
            return self.members.get_active(project.id, user.id) is not None
        return False

    def check_access(self, project_id: int, current_user: User) -> Project:
        project = self.get_project(project_id)
        if not self._can_access(project, current_user):
            raise ProjectForbiddenError(project_id)
        return project

    def accessible_project_ids_for(self, current_user: User):
        """cross-project 조회(최근 문서/검색 등)에서 쓴다. admin 이면 필터 불필요라 None."""
        if _is_admin(current_user):
            return None
        return self.repository.accessible_project_ids_subquery(current_user.id)

    def check_owner(self, project_id: int, current_user: User) -> Project:
        """삭제/visibility 전환/멤버 관리처럼 owner(또는 admin) 전용인 작업."""
        project = self.get_project(project_id)
        if _is_admin(current_user) or project.owner_id == current_user.id:
            return project
        raise ProjectForbiddenError(project_id)

    # ── CRUD ──

    def create_project(self, data: ProjectCreate, current_user: User) -> Project:
        project = self.repository.create(
            data, created_by=str(current_user.id), owner_id=current_user.id
        )
        self.members.add(
            project_id=project.id,
            user_id=current_user.id,
            role=ROLE_OWNER,
            invited_by=None,
            status=MEMBER_STATUS_ACTIVE,
        )
        return project

    def update_project(self, project_id: int, data: ProjectUpdate) -> Project:
        project = self.get_project(project_id)
        return self.repository.update(project, data)

    def update_visibility(self, project_id: int, visibility: str) -> Project:
        project = self.get_project(project_id)
        return self.repository.update_visibility(project, visibility)

    def delete_project(self, project_id: int) -> None:
        project = self.get_project(project_id)
        self.repository.delete(project)

    # ── 멤버 관리 ──

    @staticmethod
    def _to_member_read(member: ProjectMember, user: User) -> ProjectMemberRead:
        return ProjectMemberRead(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=member.role,
            status=member.status,
            invited_by=member.invited_by,
            created_at=member.created_at,
            responded_at=member.responded_at,
        )

    def list_members(self, project_id: int) -> list[ProjectMemberRead]:
        """정식 멤버(active) + 수락 대기(pending) + 거절(rejected)을 모두 돌려준다"""
        self.get_project(project_id)
        return [
            self._to_member_read(member, user)
            for member, user in self.members.list_with_user(project_id)
        ]

    def invite_member(
        self,
        project_id: int,
        *,
        email: str | None = None,
        user_id: int | None = None,
        invited_by: User,
    ) -> ProjectMemberRead:
        """초대장을 만든다"""
        self.get_project(project_id)
        if user_id is not None:
            invitee = self.users.get(user_id)
            identifier = str(user_id)
        else:
            invitee = self.users.get_by_email((email or "").strip())
            identifier = email or ""
        if invitee is None or not invitee.is_active:
            raise InviteeNotFoundError(identifier)

        existing = self.members.get(project_id, invitee.id)
        if existing is None:
            member = self.members.add(
                project_id=project_id,
                user_id=invitee.id,
                role=ROLE_MEMBER,
                invited_by=invited_by.id,
                status=MEMBER_STATUS_PENDING,
            )
        elif existing.status == MEMBER_STATUS_ACTIVE:
            raise ProjectMemberAlreadyExistsError(project_id, invitee.id)
        elif existing.status == MEMBER_STATUS_PENDING:
            raise ProjectMemberInvitePendingError(project_id, invitee.id)
        else:
            # 거절했던 사람 재초대 — 같은 행을 pending 으로 되돌린다.
            member = self.members.mark_invited(existing, invited_by=invited_by.id)
        return self._to_member_read(member, invitee)

    # ── 초대 수락/거절 (초대받은 사람 본인) ──

    def list_invitations(self, current_user: User) -> list[ProjectInvitationRead]:
        return [
            ProjectInvitationRead(
                project_id=project.id,
                project_name=project.name,
                project_description=project.description,
                visibility=project.visibility,
                invited_by=member.invited_by,
                invited_by_name=inviter.name if inviter else None,
                invited_by_email=inviter.email if inviter else None,
                invited_at=member.created_at,
            )
            for member, project, inviter in self.members.list_pending_for_user(
                current_user.id
            )
        ]

    def _pending_invitation(self, project_id: int, current_user: User) -> tuple[Project, ProjectMember]:
        project = self.get_project(project_id)
        member = self.members.get(project_id, current_user.id)
        if member is None or member.status != MEMBER_STATUS_PENDING:
            raise ProjectInvitationNotFoundError(project_id, current_user.id)
        return project, member

    def accept_invitation(self, project_id: int, current_user: User) -> InvitationOutcome:
        project, member = self._pending_invitation(project_id, current_user)
        member = self.members.set_status(member, MEMBER_STATUS_ACTIVE)
        return InvitationOutcome(project, member, member.invited_by or project.owner_id)

    def decline_invitation(self, project_id: int, current_user: User) -> InvitationOutcome:
        project, member = self._pending_invitation(project_id, current_user)
        member = self.members.set_status(member, MEMBER_STATUS_REJECTED)
        return InvitationOutcome(project, member, member.invited_by or project.owner_id)

    def remove_member(self, project_id: int, user_id: int) -> str:
        """정식 멤버 제거와 수락 전 초대 취소를 겸한다 — 행을 지우므로 재초대가 가능하다.
        지워진 행의 status 를 돌려주니 라우터가 "초대 취소"와 "멤버 제거"를 구분해 알릴 수 있다."""
        project = self.get_project(project_id)
        if project.owner_id == user_id:
            raise ProjectForbiddenError(project_id)
        member = self.members.get(project_id, user_id)
        if member is None:
            raise ProjectMemberNotFoundError(project_id, user_id)
        removed_status = member.status
        self.members.remove(member)
        return removed_status


def get_project_service(db: Session = Depends(get_db)) -> ProjectService:
    return ProjectService(ProjectRepository(db), ProjectMemberRepository(db), UserRepository(db))
