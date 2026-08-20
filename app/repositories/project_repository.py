from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.project import VISIBILITY_INVITE, VISIBILITY_PUBLIC, Project
from app.models.project_member import MEMBER_STATUS_ACTIVE, ProjectMember
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectRepository:
    """projects 테이블에 대한 DB 접근 계층."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[Project]:
        """전체 목록 — admin 전용(가시성 필터링 없음)"""
        return list(self.db.scalars(select(Project).order_by(Project.id)))

    @staticmethod
    def _accessible_condition(user_id: int):
        member_invite_ids = (
            select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.user_id == user_id,
                ProjectMember.status == MEMBER_STATUS_ACTIVE,
                Project.visibility == VISIBILITY_INVITE,
            )
        )
        return or_(
            Project.visibility == VISIBILITY_PUBLIC,
            Project.owner_id == user_id,
            Project.id.in_(member_invite_ids),
        )

    def list_accessible(self, user_id: int) -> list[Project]:
        """public 전체 + 본인 소유(private 포함) + 본인이 초대된 invite 프로젝트"""
        stmt = select(Project).where(self._accessible_condition(user_id)).order_by(Project.id)
        return list(self.db.scalars(stmt))

    def accessible_project_ids_subquery(self, user_id: int):
        """다른 테이블(documents 등)을 이 사용자가 접근 가능한 프로젝트로 좁힐 때 쓰는 서브쿼리"""
        return select(Project.id).where(self._accessible_condition(user_id))

    def get(self, project_id: int) -> Project | None:
        return self.db.get(Project, project_id)

    def create(self, data: ProjectCreate, created_by: str | None, owner_id: int | None) -> Project:
        project = Project(
            name=data.name,
            description=data.description,
            created_by=created_by,
            owner_id=owner_id,
            visibility=data.visibility,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update(self, project: Project, data: ProjectUpdate) -> Project:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update_visibility(self, project: Project, visibility: str) -> Project:
        project.visibility = visibility
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project: Project) -> None:
        self.db.delete(project)
        self.db.commit()
