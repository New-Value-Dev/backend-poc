from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.project import Project


class DashboardRepository:
    """대시보드 집계 전용 읽기 계층"""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _scope(stmt: Select, project_id: int | None) -> Select:
        """Document 가 걸린 쿼리에 프로젝트 스코프를 덧붙인다"""
        if project_id is None:
            return stmt
        return stmt.where(Document.project_id == project_id)

    # ── 카운트 ──

    def count_projects(
        self, project_id: int | None = None, created_by: str | None = None
    ) -> int:
        stmt = select(func.count()).select_from(Project)
        if project_id is not None:
            stmt = stmt.where(Project.id == project_id)
        if created_by is not None:
            stmt = stmt.where(Project.created_by == created_by)
        return self.db.scalar(stmt) or 0

    def count_documents(
        self, project_id: int | None = None, created_by: str | None = None
    ) -> int:
        stmt = self._scope(select(func.count()).select_from(Document), project_id)
        if created_by is not None:
            stmt = stmt.where(Document.created_by == created_by)
        return self.db.scalar(stmt) or 0

    # ── 파이프라인 / 유형 분포 ──

    def pipeline_counts(
        self, project_id: int | None = None, created_by: str | None = None
    ) -> list[tuple[str, int]]:
        """문서의 '현재 버전' processing_status 별 문서 수"""
        status = func.coalesce(DocumentVersion.processing_status, "UPLOADED").label(
            "status"
        )
        stmt = (
            select(status, func.count().label("count"))
            .select_from(Document)
            .outerjoin(DocumentVersion, Document.current_version_id == DocumentVersion.id)
            .group_by(status)
        )
        stmt = self._scope(stmt, project_id)
        if created_by is not None:
            stmt = stmt.where(Document.created_by == created_by)
        return [(row.status, row.count) for row in self.db.execute(stmt)]

    def document_type_counts(
        self, project_id: int | None = None
    ) -> list[tuple[str | None, int]]:
        """document_type 별 문서 수"""
        count = func.count().label("count")
        stmt = (
            select(Document.document_type, count)
            .select_from(Document)
            .group_by(Document.document_type)
            .order_by(count.desc())
        )
        return [(row[0], row[1]) for row in self.db.execute(self._scope(stmt, project_id))]

    def daily_version_counts(
        self, since: datetime, project_id: int | None = None
    ) -> dict[date, int]:
        """since 이후 업로드된 버전 수를 날짜별로 집계"""
        day = func.date(DocumentVersion.created_at).label("day")
        stmt = (
            select(day, func.count().label("count"))
            .select_from(DocumentVersion)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.created_at >= since)
            .group_by(day)
        )
        return {row.day: row.count for row in self.db.execute(self._scope(stmt, project_id))}
