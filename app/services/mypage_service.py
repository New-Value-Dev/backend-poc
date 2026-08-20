from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.repositories.dashboard_repository import DashboardRepository
from app.schemas.mypage import MyPageProfile, MyPageStats, MyPageSummary
from app.services.dashboard_service import (
    IN_FLIGHT_STATUSES,
    DashboardService,
    get_dashboard_service,
)


class MyPageService:
    """dashboard/activity 는 전체(또는 project_id) 기준이라 로그인 사용자 전용 집계가 따로 필요"""

    def __init__(self, repository: DashboardRepository, dashboard: DashboardService) -> None:
        self.repository = repository
        self.dashboard = dashboard

    def get_summary(self, user: User, *, activity_limit: int = 10) -> MyPageSummary:
        created_by = str(user.id)
        pipeline = dict(self.repository.pipeline_counts(created_by=created_by))
        stats = MyPageStats(
            projects=self.repository.count_projects(created_by=created_by),
            documents=self.repository.count_documents(created_by=created_by),
            processing=sum(
                count for status, count in pipeline.items() if status in IN_FLIGHT_STATUSES
            ),
        )
        profile = MyPageProfile(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            provider=user.provider,
            last_login_at=user.last_login_at,
            member_since=user.created_at,
        )
        recent_activity = self.dashboard.get_activity(limit=activity_limit, actor_id=user.id)
        return MyPageSummary(profile=profile, stats=stats, recent_activity=recent_activity)


def get_mypage_service(
    db: Session = Depends(get_db),
    dashboard: DashboardService = Depends(get_dashboard_service),
) -> MyPageService:
    return MyPageService(DashboardRepository(db), dashboard)
