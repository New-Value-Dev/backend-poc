from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.folder import Folder


class FolderRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_project(self, project_id: int) -> list[Folder]:
        return list(
            self.db.scalars(
                select(Folder)
                .where(Folder.project_id == project_id)
                .order_by(Folder.parent_id.nulls_first(), Folder.id)
            )
        )

    def get(self, folder_id: int) -> Folder | None:
        return self.db.get(Folder, folder_id)

    def create(self, *, project_id: int, name: str, parent_id: int | None) -> Folder:
        folder = Folder(project_id=project_id, name=name, parent_id=parent_id)
        self.db.add(folder)
        self.db.commit()
        self.db.refresh(folder)
        return folder

    def update(self, folder: Folder, values: dict) -> Folder:
        for field, value in values.items():
            setattr(folder, field, value)
        self.db.commit()
        self.db.refresh(folder)
        return folder

    def delete(self, folder: Folder) -> None:
        self.db.delete(folder)
        self.db.commit()
