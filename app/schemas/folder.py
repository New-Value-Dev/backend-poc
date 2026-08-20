from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: int | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: int | None = None


class FolderReorder(BaseModel):
    """폴더 순서 변경"""

    parent_id: int | None = None
    target_index: int = Field(..., ge=0, description="이동할 부모 내에서의 0-based 목표 위치")


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    parent_id: int | None
    name: str
    rank: int
    created_at: datetime
