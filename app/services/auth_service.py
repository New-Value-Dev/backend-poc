from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.auth_providers import ExternalIdentity


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    def get_or_create_user(self, identity: ExternalIdentity) -> User:
        user = self.users.get_by_provider(identity.provider, identity.sub)
        if user is None:
            # 같은 이메일이 다른 provider 로 이미 있으면 그 계정을 재사용
            user = self.users.get_by_email(identity.email)
        if user is None:
            user = self.users.create(
                email=identity.email,
                name=identity.name,
                provider=identity.provider,
                provider_sub=identity.sub,
                role="member",
            )
        else:
            if identity.name:
                user.name = identity.name
        user.last_login_at = datetime.now(timezone.utc)
        return self.users.save(user)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db))
