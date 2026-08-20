from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.activity_repository import ActivityLogRepository
from app.repositories.dashboard_repository import DashboardRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.dashboard import (
    ActivityItem,
    DashboardStats,
    DashboardSummary,
    DocumentTypeCount,
    PipelineStage,
)
from app.schemas.document import ProcessingStatus
from app.services.activity_service import describe
from app.services.project_service import ProjectNotFoundError

PIPELINE_ORDER = tuple(s.value for s in ProcessingStatus)
IN_FLIGHT_STATUSES = frozenset({"PARSING", "CHUNKING", "EMBEDDING"})

WEEK_DAYS = 7
UNKNOWN_TYPE_LABEL = "기타"
UNKNOWN_ACTOR = "알 수 없음"


class DashboardService:
    def __init__(
        self,
        repository: DashboardRepository,
        activity_logs: ActivityLogRepository,
        projects: ProjectRepository,
    ) -> None:
        self.repository = repository
        self.activity_logs = activity_logs
        self.projects = projects

    def _ensure_project(self, project_id: int | None) -> None:
        """없는 project_id 는 404 로 끊음"""
        if project_id is not None and self.projects.get(project_id) is None:
            raise ProjectNotFoundError(project_id)

    # ── GET /dashboard/summary ──

    def get_summary(self, *, project_id: int | None = None) -> DashboardSummary:
        self._ensure_project(project_id)
        pipeline = dict(self.repository.pipeline_counts(project_id))
        return DashboardSummary(
            stats=DashboardStats(
                projects=self.repository.count_projects(project_id),
                documents=self.repository.count_documents(project_id),
                processing=sum(
                    count
                    for status, count in pipeline.items()
                    if status in IN_FLIGHT_STATUSES
                ),
                # RAG 는 아직 미구현
                rag_today=0,
            ),
            weekly_processing=self._weekly_processing(project_id),
            document_types=[
                DocumentTypeCount(label=doc_type or UNKNOWN_TYPE_LABEL, value=count)
                for doc_type, count in self.repository.document_type_counts(project_id)
            ],
            pipeline=self._pipeline_stages(pipeline),
        )

    def _weekly_processing(self, project_id: int | None) -> list[int]:
        """최근 7일(오늘 포함) 업로드 건수를 과거 → 오늘 순"""
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=WEEK_DAYS - 1)
        counts = self.repository.daily_version_counts(
            datetime.combine(start, time.min, tzinfo=timezone.utc), project_id
        )
        return [counts.get(start + timedelta(days=i), 0) for i in range(WEEK_DAYS)]

    @staticmethod
    def _pipeline_stages(counts: dict[str, int]) -> list[PipelineStage]:
        stages = [
            PipelineStage(status=status, count=counts.get(status, 0))
            for status in PIPELINE_ORDER
        ]
        stages.extend(
            PipelineStage(status=status, count=count)
            for status, count in counts.items()
            if status not in PIPELINE_ORDER
        )
        return stages

    # ── GET /activity ──

    def get_activity(
        self,
        *,
        limit: int = 10,
        project_id: int | None = None,
        action: str | None = None,
        actor_id: int | None = None,
    ) -> list[ActivityItem]:
        """activity_logs 를 최신순으로 읽어 표시용으로 풀어 줌.

        actor_id 는 공개 /activity 라우트에는 노출하지 않고, MyPageService 가
        "내 활동"만 걸러낼 때 내부적으로 재사용한다.
        """
        self._ensure_project(project_id)
        logs = self.activity_logs.list_recent(
            limit=limit, project_id=project_id, action=action, actor_id=actor_id
        )

        ids_by_type: dict[str, set[int]] = defaultdict(set)
        for log in logs:
            if log.target_type and log.target_id is not None:
                ids_by_type[log.target_type].add(log.target_id)
        alive = self.activity_logs.existing_targets(ids_by_type)

        items = []
        for log in logs:
            phrase, kind = describe(log)
            items.append(
                ActivityItem(
                    actor=log.actor_label or UNKNOWN_ACTOR,
                    action=phrase,
                    target=log.target_label or "",
                    kind=kind,
                    at=log.created_at,
                    target_type=log.target_type,
                    target_id=log.target_id,
                    target_alive=(log.target_type, log.target_id) in alive,
                )
            )
        return items


def get_dashboard_service(db: Session = Depends(get_db)) -> DashboardService:
    return DashboardService(
        DashboardRepository(db), ActivityLogRepository(db), ProjectRepository(db)
    )
