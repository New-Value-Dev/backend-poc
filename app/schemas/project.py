from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Visibility = Literal["private", "invite", "public"]
MemberRole = Literal["owner", "member"]
MemberStatus = Literal["pending", "active", "rejected"]


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    visibility: Visibility = "public"
    # created_by/owner_id 는 클라이언트가 지정하지 않는다 — 서버가 로그인 사용자로 채운다


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ProjectVisibilityUpdate(BaseModel):
    visibility: Visibility


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    created_by: str | None
    owner_id: int | None
    visibility: Visibility
    created_at: datetime
    updated_at: datetime


class ProjectMemberInvite(BaseModel):
    """user_id또는 email 중 하나를 보낸다."""

    email: str | None = Field(
        default=None, min_length=3, max_length=320, description="초대할 사용자의 로그인 이메일"
    )
    user_id: int | None = Field(
        default=None, description="초대할 사용자 id (GET /users/search 로 찾은 값)"
    )

    @model_validator(mode="after")
    def _require_one(self) -> "ProjectMemberInvite":
        if (self.user_id is None) == (self.email is None):
            raise ValueError("user_id 또는 email 중 정확히 하나를 보내야 합니다")
        return self


class ProjectMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: str
    name: str | None
    role: MemberRole
    status: MemberStatus
    invited_by: int | None
    created_at: datetime
    responded_at: datetime | None = None


class ProjectInvitationRead(BaseModel):
    """내가 받은 수락 대기 초대 한 건."""

    project_id: int
    project_name: str
    project_description: str | None
    visibility: Visibility
    invited_by: int | None
    invited_by_name: str | None
    invited_by_email: str | None
    invited_at: datetime
