from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProcessingStatus(str, Enum):
    """document_versions.processing_status 값 — 업로드 후 처리 파이프라인 상태
    UPLOADED → PARSING → PARSED → CHUNKING → CHUNKED → EMBEDDING → READY"""

    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    CHUNKING = "CHUNKING"
    CHUNKED = "CHUNKED"
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    FAILED = "FAILED"


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_no: int
    original_file_name: str
    mime_type: str | None
    file_size: int | None
    checksum: str | None
    processing_status: str
    parser_version: str | None
    created_at: datetime


class AuthorInfo(BaseModel):
    id: int | None
    name: str | None
    email: str | None


class DocumentMove(BaseModel):
    """개인 프로젝트에서 완성한 문서를 다른 프로젝트로 옮길 때"""

    project_id: int | None = Field(
        default=None,
        description="옮길 대상 프로젝트 id. 생략하면 현재 프로젝트를 유지한 채 folder_id만 바뀐다",
    )
    folder_id: int | None = Field(
        default=None, description="대상 프로젝트 내 폴더 id. 생략하면 최상위(폴더 없음)로 이동"
    )


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    folder_id: int | None
    name: str
    description: str | None
    document_type: str | None
    # status 는 없다 — 처리 상태는 current_version.processing_status 를 볼 것.
    current_version_id: int | None
    created_by: str | None
    # 작성자 이름/이메일(created_by 사용자 id 를 해석) + 현재 버전 정보
    author: AuthorInfo | None = None
    current_version: DocumentVersionRead | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    document: DocumentRead
    version: DocumentVersionRead


class VersionStatusResponse(BaseModel):
    version_id: int
    status: str
    progress: int  # 0~100


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_version_id: int
    parent_section_id: int | None
    title: str | None
    section_type: str | None
    level: int | None
    page_start: int | None
    page_end: int | None
    order_no: int
    content: str | None
    meta: dict | None


class RecentDocumentRead(BaseModel):
    """대시보드 최근 문서 카드용"""

    id: int
    name: str
    project_id: int
    project_name: str
    # 현재 버전의 processing_status. 버전이 아직 없으면 UPLOADED 로 본다.
    processing_status: str
    created_at: datetime


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    document_id: int
    document_version_id: int
    section_id: int | None
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    # ORM 속성명은 chunk_metadata(컬럼 metadata) → 응답 키는 metadata
    metadata: dict | None = Field(default=None, validation_alias="chunk_metadata")
