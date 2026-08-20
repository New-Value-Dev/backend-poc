from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.folder import Folder

RANK_STEP = 1000


class FolderRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_project(self, project_id: int) -> list[Folder]:
        return list(
            self.db.scalars(
                select(Folder)
                .where(Folder.project_id == project_id)
                .order_by(Folder.parent_id.nulls_first(), Folder.rank, Folder.id)
            )
        )

    def list_siblings(self, project_id: int, parent_id: int | None) -> list[Folder]:
        stmt = select(Folder).where(Folder.project_id == project_id)
        stmt = stmt.where(
            Folder.parent_id.is_(None) if parent_id is None else Folder.parent_id == parent_id
        )
        return list(self.db.scalars(stmt.order_by(Folder.rank, Folder.id)))

    def get(self, folder_id: int) -> Folder | None:
        return self.db.get(Folder, folder_id)

    def next_rank(self, project_id: int, parent_id: int | None) -> int:
        stmt = select(func.max(Folder.rank)).where(Folder.project_id == project_id)
        stmt = stmt.where(
            Folder.parent_id.is_(None) if parent_id is None else Folder.parent_id == parent_id
        )
        max_rank = self.db.scalar(stmt)
        return (max_rank + RANK_STEP) if max_rank is not None else 0

    def create(self, *, project_id: int, name: str, parent_id: int | None) -> Folder:
        folder = Folder(
            project_id=project_id,
            name=name,
            parent_id=parent_id,
            rank=self.next_rank(project_id, parent_id),
        )
        self.db.add(folder)
        self.db.commit()
        self.db.refresh(folder)
        return folder

    def set_ranks(self, ordered_folders: list[Folder]) -> None:
        """순서대로 rank를 재부여한다"""
        for index, folder in enumerate(ordered_folders):
            folder.rank = index * RANK_STEP

    def commit(self) -> None:
        self.db.commit()

    def update(self, folder: Folder, values: dict) -> Folder:
        for field, value in values.items():
            setattr(folder, field, value)
        self.db.commit()
        self.db.refresh(folder)
        return folder

    def delete(self, folder: Folder) -> None:
        self.db.delete(folder)
        self.db.commit()
