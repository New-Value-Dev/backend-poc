from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_many(self, user_ids: set[int]) -> list[User]:
        if not user_ids:
            return []
        return list(self.db.scalars(select(User).where(User.id.in_(user_ids))))

    def get_by_provider(self, provider: str, provider_sub: str) -> User | None:
        return self.db.scalar(
            select(User).where(
                User.provider == provider, User.provider_sub == provider_sub
            )
        )

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email))

    def create(
        self, *, email: str, name: str | None, provider: str, provider_sub: str, role: str
    ) -> User:
        user = User(
            email=email,
            name=name,
            provider=provider,
            provider_sub=provider_sub,
            role=role,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def save(self, user: User) -> User:
        self.db.commit()
        self.db.refresh(user)
        return user
