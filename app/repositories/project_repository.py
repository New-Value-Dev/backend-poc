from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectRepository:
    """projects 테이블에 대한 DB 접근 계층."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[Project]:
        return list(self.db.scalars(select(Project).order_by(Project.id)))

    def get(self, project_id: int) -> Project | None:
        return self.db.get(Project, project_id)

    def create(self, data: ProjectCreate, created_by: str | None) -> Project:
        project = Project(
            name=data.name,
            description=data.description,
            created_by=created_by,
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

    def delete(self, project: Project) -> None:
        self.db.delete(project)
        self.db.commit()
