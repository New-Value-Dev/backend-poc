from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    body: str | None
    # 클릭 시 이동할 프론트 경로 (없으면 이동 대상 없음)
    url: str | None
    meta: dict[str, Any] | None
    # None 이면 안 읽음
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationRead]
    # 목록 필터와 무관한 전체 미읽음 수 (뱃지용) — items 길이와 다를 수 있다
    unread: int


class UnreadCountResponse(BaseModel):
    unread: int
