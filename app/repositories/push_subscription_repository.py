from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.push_subscription import PushSubscription


class PushSubscriptionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_user(self, user_id: int) -> list[PushSubscription]:
        return list(
            self.db.scalars(
                select(PushSubscription).where(PushSubscription.user_id == user_id)
            )
        )

    def get_by_endpoint(self, endpoint: str) -> PushSubscription | None:
        return self.db.scalar(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )

    def upsert(
        self,
        *,
        user_id: int,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
    ) -> PushSubscription:
        sub = self.get_by_endpoint(endpoint)
        if sub is None:
            sub = PushSubscription(user_id=user_id, endpoint=endpoint)
            self.db.add(sub)
        sub.user_id = user_id
        sub.p256dh = p256dh
        sub.auth = auth
        sub.user_agent = user_agent
        self.db.commit()
        self.db.refresh(sub)
        return sub

    def delete_by_endpoint(self, endpoint: str) -> None:
        sub = self.get_by_endpoint(endpoint)
        if sub is not None:
            self.db.delete(sub)
            self.db.commit()

    def delete(self, subscription: PushSubscription) -> None:
        self.db.delete(subscription)
        self.db.commit()
