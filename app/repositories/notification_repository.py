from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.notification import Notification


class NotificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        user_id: int,
        type: str,
        title: str,
        body: str | None,
        url: str | None,
        meta: dict[str, Any] | None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id, type=type, title=title, body=body, url=url, meta=meta
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def get(self, notification_id: int) -> Notification | None:
        return self.db.get(Notification, notification_id)

    def list_for_user(
        self, user_id: int, *, only_unread: bool = False, limit: int = 20, offset: int = 0
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if only_unread:
            stmt = stmt.where(Notification.read_at.is_(None))
        stmt = (
            stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt))

    def count_unread(self, user_id: int) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            )
            or 0
        )

    def mark_read(self, notification: Notification) -> Notification:
        if notification.read_at is None:
            notification.read_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(notification)
        return notification

    def mark_all_read(self, user_id: int) -> int:
        """안 읽은 알림을 모두 읽음 처리하고 처리된 건수를 돌려준다."""
        result = self.db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=datetime.now(timezone.utc))
        )
        self.db.commit()
        return result.rowcount or 0
