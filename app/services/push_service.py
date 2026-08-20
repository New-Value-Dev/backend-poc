from __future__ import annotations

import json
import logging

from fastapi import Depends
from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.repositories.push_subscription_repository import PushSubscriptionRepository
from app.schemas.push import PushSubscribeRequest, PushUnsubscribeRequest

logger = logging.getLogger(__name__)


class PushService:
    def __init__(self, repository: PushSubscriptionRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def public_key(self) -> str | None:
        return self.settings.vapid_public_key

    def subscribe(
        self, user: User, req: PushSubscribeRequest, *, user_agent: str | None
    ) -> None:
        self.repository.upsert(
            user_id=user.id,
            endpoint=req.endpoint,
            p256dh=req.keys.p256dh,
            auth=req.keys.auth,
            user_agent=user_agent,
        )

    def unsubscribe(self, req: PushUnsubscribeRequest) -> None:
        self.repository.delete_by_endpoint(req.endpoint)

    def notify_user(
        self,
        user_id: int,
        *,
        title: str,
        body: str,
        url: str | None = None,
        type: str | None = None,
    ) -> None:
        """user_id의 모든 구독에 발송한다"""
        if not self.settings.vapid_private_key or not self.settings.vapid_public_key:
            logger.warning("VAPID 키가 설정되지 않아 push 발송을 건너뜀")
            return

        payload = json.dumps({"title": title, "body": body, "url": url, "type": type})
        for sub in self.repository.list_by_user(user_id):
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=payload,
                    vapid_private_key=self.settings.vapid_private_key,
                    vapid_claims={"sub": self.settings.vapid_claims_email},
                )
            except WebPushException as exc:
                status_code = (
                    exc.response.status_code if exc.response is not None else None
                )
                if status_code in (404, 410):
                    # 브라우저에서 구독이 만료/취소된 경우 — 조용히 정리
                    self.repository.delete(sub)
                else:
                    logger.warning(
                        "push 발송 실패: user_id=%s status=%s",
                        user_id, status_code, exc_info=True,
                    )
            except Exception:
                logger.warning("push 발송 중 예외: user_id=%s", user_id, exc_info=True)


def get_push_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PushService:
    return PushService(PushSubscriptionRepository(db), settings)


def push_service_for(db: Session, settings: Settings | None = None) -> PushService:
    """DI 밖(백그라운드 작업)에서 세션을 직접 들고 만들 때."""
    return PushService(PushSubscriptionRepository(db), settings or get_settings())
