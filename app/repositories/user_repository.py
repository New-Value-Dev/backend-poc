from sqlalchemy import case, nulls_last, or_, select
from sqlalchemy.orm import Session

from app.models.user import User

# ILIKE 패턴에서 특별한 의미를 갖는 문자 — 사용자가 입력한 걸 리터럴로 취급해야 한다.
_LIKE_ESCAPE = "\\"


def _like_pattern(value: str, *, prefix_only: bool = False) -> str:
    escaped = (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )
    return f"{escaped}%" if prefix_only else f"%{escaped}%"


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

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        exclude_user_ids: set[int] | None = None,
    ) -> list[User]:
        """이름/이메일 부분일치(대소문자 무시)"""
        contains = _like_pattern(query)
        prefix = _like_pattern(query, prefix_only=True)
        rank = case(
            (User.email.ilike(prefix, escape=_LIKE_ESCAPE), 0),
            (User.name.ilike(prefix, escape=_LIKE_ESCAPE), 1),
            else_=2,
        )
        stmt = (
            select(User)
            .where(
                User.is_active.is_(True),
                or_(
                    User.email.ilike(contains, escape=_LIKE_ESCAPE),
                    User.name.ilike(contains, escape=_LIKE_ESCAPE),
                ),
            )
            .order_by(rank, nulls_last(User.name.asc()), User.email)
            .limit(limit)
        )
        if exclude_user_ids:
            stmt = stmt.where(User.id.notin_(exclude_user_ids))
        return list(self.db.scalars(stmt))

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
