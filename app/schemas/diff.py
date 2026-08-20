from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DiffToken(BaseModel):
    """git diff 스타일 렌더링용 토큰 하나. 프론트가 순서대로 이어붙이면 원문이 재구성된다."""

    op: Literal["equal", "insert", "delete"]
    text: str


class SectionDiff(BaseModel):
    op: Literal["unchanged", "added", "deleted", "modified"]
    from_section_id: int | None
    to_section_id: int | None
    level: int | None
    section_type: str | None
    title: str | None
    tokens: list[DiffToken]


class DiffSummary(BaseModel):
    added: int
    deleted: int
    modified: int
    unchanged: int


class VersionRef(BaseModel):
    id: int
    version_no: int


class DiffResult(BaseModel):
    document_id: int
    from_version: VersionRef
    to_version: VersionRef
    sections: list[SectionDiff]
    summary: DiffSummary
