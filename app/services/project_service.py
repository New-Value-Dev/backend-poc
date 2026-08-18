from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.project import Project
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectNotFoundError(Exception):
    """요청한 프로젝트가 존재하지 않을 때 발생."""

    def __init__(self, project_id: int) -> None:
        self.project_id = project_id
        super().__init__(f"Project {project_id} not found")


class ProjectService:
    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository

    def list_projects(self) -> list[Project]:
        return self.repository.list()

    def get_project(self, project_id: int) -> Project:
        project = self.repository.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    def create_project(self, data: ProjectCreate, created_by: str | None = None) -> Project:
        return self.repository.create(data, created_by)

    def update_project(self, project_id: int, data: ProjectUpdate) -> Project:
        project = self.get_project(project_id)
        return self.repository.update(project, data)

    def delete_project(self, project_id: int) -> None:
        project = self.get_project(project_id)
        self.repository.delete(project)


def get_project_service(db: Session = Depends(get_db)) -> ProjectService:
    return ProjectService(ProjectRepository(db))
