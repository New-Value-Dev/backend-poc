from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.document import Document
from app.models.folder import Folder
from app.models.project import Project

# target_type 
TARGET_MODELS = {
    "document": Document,
    "project": Project,
    "folder": Folder,
}


class ActivityLogRepository:
    """activity_logs 접근 계층 append + 최신순 조회만"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, log: ActivityLog) -> ActivityLog:
        self.db.add(log)
        self.db.commit()
        return log

    def list_recent(
        self,
        *,
        limit: int,
        project_id: int | None = None,
        action: str | None = None,
    ) -> list[ActivityLog]:
        stmt = select(ActivityLog)
        if project_id is not None:
            stmt = stmt.where(ActivityLog.project_id == project_id)
        if action is not None:
            stmt = stmt.where(ActivityLog.action == action)
        # created_at 만으로는 같은 초에 들어온 행의 순서가 흔들려서 id 를 tiebreaker 로 쓴다.
        stmt = stmt.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        return list(self.db.scalars(stmt.limit(limit)))

    def existing_targets(
        self, ids_by_type: dict[str, set[int]]
    ) -> set[tuple[str, int]]:
        """아직 살아 있는 대상만"""
        alive: set[tuple[str, int]] = set()
        for target_type, ids in ids_by_type.items():
            model = TARGET_MODELS.get(target_type)
            if model is None or not ids:
                continue
            found = self.db.scalars(select(model.id).where(model.id.in_(ids)))
            alive.update((target_type, row_id) for row_id in found)
        return alive
