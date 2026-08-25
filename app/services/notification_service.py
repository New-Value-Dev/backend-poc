from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository
from app.services.push_service import PushService, push_service_for

logger = logging.getLogger(__name__)


class NotificationType:
    """알림 종류 코드. 프론트가 아이콘/그룹핑에 쓰므로 값이 곧 계약이다."""

    PROJECT_INVITE = "project.invite"
    PROJECT_INVITE_ACCEPTED = "project.invite_accepted"
    PROJECT_INVITE_DECLINED = "project.invite_declined"
    PROJECT_MEMBER_REMOVED = "project.member_removed"

    ANALYSIS_COMPLETE = "analysis.complete"
    ANALYSIS_FAIL = "analysis.fail"


class NotificationNotFoundError(Exception):
    def __init__(self, notification_id: int) -> None:
        self.notification_id = notification_id
        super().__init__(f"Notification {notification_id} not found")


class NotificationService:
    """인앱 알림함 + Web Push 를 한 곳에서 처리"""

    def __init__(self, repository: NotificationRepository, push: PushService) -> None:
        self.repository = repository
        self.push = push

    # ── 발송 ──

    def notify(
        self,
        user_id: int,
        *,
        type: str,
        title: str,
        body: str | None = None,
        url: str | None = None,
        meta: dict[str, Any] | None = None,
        push: bool = True,
    ) -> None:
        try:
            self.repository.add(
                user_id=user_id, type=type, title=title, body=body, url=url, meta=meta
            )
        except Exception:
            logger.warning("알림 저장 실패: type=%s user_id=%s", type, user_id, exc_info=True)
            try:
                self.repository.db.rollback()
            except Exception:
                logger.exception("알림 저장 롤백 실패")
        if push:
            # push_service 쪽이 자체적으로 예외를 먹고 로깅한다.
            self.push.notify_user(
                user_id, title=title, body=body or "", url=url, type=type
            )

    # ── 조회/읽음 ──

    def list_for_user(
        self, user: User, *, only_unread: bool = False, limit: int = 20, offset: int = 0
    ) -> tuple[list[Notification], int]:
        items = self.repository.list_for_user(
            user.id, only_unread=only_unread, limit=limit, offset=offset
        )
        return items, self.repository.count_unread(user.id)

    def unread_count(self, user: User) -> int:
        return self.repository.count_unread(user.id)

    def mark_read(self, user: User, notification_id: int) -> Notification:
        notification = self.repository.get(notification_id)
        # 남의 알림은 존재 자체를 알려주지 않는다 — 403 대신 404.
        if notification is None or notification.user_id != user.id:
            raise NotificationNotFoundError(notification_id)
        return self.repository.mark_read(notification)

    def mark_all_read(self, user: User) -> int:
        return self.repository.mark_all_read(user.id)


def get_notification_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NotificationService:
    return NotificationService(NotificationRepository(db), push_service_for(db, settings))


def notification_service_for(
    db: Session, settings: Settings | None = None
) -> NotificationService:
    """DI 밖(백그라운드 작업)에서 세션을 직접 들고 만들 때."""
    resolved = settings or get_settings()
    return NotificationService(NotificationRepository(db), push_service_for(db, resolved))
