from datetime import datetime

from app.schemas.dashboard import ActivityItem, _CamelModel


class MyPageProfile(_CamelModel):
    id: int
    email: str
    name: str | None
    role: str
    provider: str
    last_login_at: datetime | None
    member_since: datetime


class MyPageStats(_CamelModel):
    """dashboard의 DashboardStats 와 달리 created_by/actor_id 로 로그인 사용자에게 스코핑됨"""

    projects: int
    documents: int
    processing: int


class MyPageSummary(_CamelModel):
    profile: MyPageProfile
    stats: MyPageStats
    recent_activity: list[ActivityItem]
