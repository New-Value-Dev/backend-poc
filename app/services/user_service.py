from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.project_member import MEMBER_STATUS_ACTIVE, MEMBER_STATUS_PENDING
from app.models.user import User
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.user_repository import UserRepository

SEARCH_MIN_LENGTH = 2


class UserService:
    def __init__(self, users: UserRepository, members: ProjectMemberRepository) -> None:
        self.users = users
        self.members = members

    def search(
        self, query: str, *, limit: int = 20, exclude_project_id: int | None = None
    ) -> list[User]:
        """멤버 초대 화면용 사용자 검색"""
        exclude: set[int] = set()
        if exclude_project_id is not None:
            exclude = self.members.list_user_ids(
                exclude_project_id,
                statuses=(MEMBER_STATUS_ACTIVE, MEMBER_STATUS_PENDING),
            )
        return self.users.search(query.strip(), limit=limit, exclude_user_ids=exclude)


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(UserRepository(db), ProjectMemberRepository(db))
