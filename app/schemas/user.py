from pydantic import BaseModel, ConfigDict


class UserSearchResult(BaseModel):
    """멤버 초대용 사용자 검색 결과"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
