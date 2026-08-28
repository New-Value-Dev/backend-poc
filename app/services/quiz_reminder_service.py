from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.timeutil import format_kst
from app.repositories.quiz_book_repository import QuizBookRepository
from app.services.notification_service import NotificationType, notification_service_for

logger = logging.getLogger(__name__)


def send_due_reminders(db: Session, settings: Settings) -> int:
    """마감이 임박했고 아직 제출하지 않은 지정자에게 리마인더를 보낸다"""
    books = QuizBookRepository(db)
    notifications = notification_service_for(db, settings)
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=settings.quiz_due_reminder_window_hours)

    candidates = books.list_due_reminder_candidates(now, window_end)
    for assignee, book in candidates:
        notifications.notify(
            assignee.user_id,
            type=NotificationType.QUIZ_DUE_SOON,
            title=f"'{book.title}' 응시 마감이 얼마 남지 않았습니다",
            body=f"마감: {format_kst(book.due_at)}",
            url=f"/quiz/{book.id}/take",
            meta={
                "quiz_book_id": book.id,
                "project_id": book.project_id,
                "due_at": book.due_at.isoformat(),
            },
        )
        assignee.due_reminder_sent_at = now
    db.commit()
    return len(candidates)


def run_due_reminder_loop(interval_seconds: int) -> None:
    """앱 기동 시 데몬 스레드로 실행"""
    while True:
        try:
            db = SessionLocal()
            try:
                sent = send_due_reminders(db, get_settings())
                if sent:
                    logger.info("퀴즈 마감 리마인더 %d건 발송", sent)
            finally:
                db.close()
        except Exception:
            logger.exception("퀴즈 마감 리마인더 처리 실패")
        time.sleep(interval_seconds)
