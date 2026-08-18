from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.folder import Folder
from app.repositories.folder_repository import FolderRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.folder import FolderCreate, FolderUpdate
from app.services.project_service import ProjectNotFoundError


class FolderNotFoundError(Exception):
    def __init__(self, folder_id: int) -> None:
        self.folder_id = folder_id
        super().__init__(f"Folder {folder_id} not found")


class FolderValidationError(Exception):
    """부모 폴더가 다른 프로젝트이거나 트리 순환을 만드는 경우."""


class FolderService:
    def __init__(self, folders: FolderRepository, projects: ProjectRepository) -> None:
        self.folders = folders
        self.projects = projects

    def _ensure_project(self, project_id: int) -> None:
        if self.projects.get(project_id) is None:
            raise ProjectNotFoundError(project_id)

    def _validate_parent(self, project_id: int, parent_id: int) -> Folder:
        parent = self.folders.get(parent_id)
        if parent is None:
            raise FolderValidationError(f"parent folder {parent_id} not found")
        if parent.project_id != project_id:
            raise FolderValidationError("parent folder belongs to another project")
        return parent

    def list_folders(self, project_id: int) -> list[Folder]:
        self._ensure_project(project_id)
        return self.folders.list_by_project(project_id)

    def get_folder(self, folder_id: int) -> Folder:
        folder = self.folders.get(folder_id)
        if folder is None:
            raise FolderNotFoundError(folder_id)
        return folder

    def create_folder(self, project_id: int, data: FolderCreate) -> Folder:
        self._ensure_project(project_id)
        if data.parent_id is not None:
            self._validate_parent(project_id, data.parent_id)
        return self.folders.create(
            project_id=project_id, name=data.name, parent_id=data.parent_id
        )

    def update_folder(self, folder_id: int, data: FolderUpdate) -> Folder:
        folder = self.get_folder(folder_id)
        values = data.model_dump(exclude_unset=True)

        if "parent_id" in values:
            new_parent_id = values["parent_id"]
            if new_parent_id is not None:
                if new_parent_id == folder.id:
                    raise FolderValidationError("folder cannot be its own parent")
                self._validate_parent(folder.project_id, new_parent_id)
                self._ensure_no_cycle(folder.id, new_parent_id)

        return self.folders.update(folder, values)

    def delete_folder(self, folder_id: int) -> None:
        folder = self.get_folder(folder_id)
        self.folders.delete(folder)

    def _ensure_no_cycle(self, folder_id: int, new_parent_id: int) -> None:
        """새 부모의 조상 중에 자기 자신이 있으면 순환이므로 거부한다."""
        cursor = self.folders.get(new_parent_id)
        while cursor is not None:
            if cursor.id == folder_id:
                raise FolderValidationError("cannot move a folder under its own descendant")
            cursor = self.folders.get(cursor.parent_id) if cursor.parent_id else None


def get_folder_service(db: Session = Depends(get_db)) -> FolderService:
    return FolderService(FolderRepository(db), ProjectRepository(db))
