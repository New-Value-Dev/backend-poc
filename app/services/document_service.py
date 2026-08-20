from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.repositories.document_repository import (
    DocumentRepository,
    DocumentVersionRepository,
)
from app.repositories.folder_repository import FolderRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.document import (
    AuthorInfo,
    DocumentRead,
    DocumentVersionRead,
    RecentDocumentRead,
)
from app.services.project_service import ProjectNotFoundError
from app.services.storage import LocalStorageProvider, StorageProvider

# processing_status -> 진행률매핑
_STATUS_PROGRESS = {
    "UPLOADED": 5,
    "PARSING": 25,
    "PARSED": 45,
    "CHUNKING": 65,
    "CHUNKED": 75,
    "EMBEDDING": 85,
    "READY": 100,
    "FAILED": 0,
}


class DocumentNotFoundError(Exception):
    def __init__(self, document_id: int) -> None:
        self.document_id = document_id
        super().__init__(f"Document {document_id} not found")


class VersionNotFoundError(Exception):
    def __init__(self, version_id: int) -> None:
        self.version_id = version_id
        super().__init__(f"Version {version_id} not found")


class DocumentValidationError(Exception):
    """확장자/용량/폴더 검증 실패."""


def status_progress(status: str) -> int:
    return _STATUS_PROGRESS.get(status, 0)


def _author_id(created_by: str | None) -> int | None:
    """created_by(임시 String, 사용자 id 보관)를 int id 로 해석. 아니면 None."""
    if created_by and created_by.isdigit():
        return int(created_by)
    return None


class DocumentService:
    def __init__(
        self,
        documents: DocumentRepository,
        versions: DocumentVersionRepository,
        projects: ProjectRepository,
        folders: FolderRepository,
        users: UserRepository,
        storage: StorageProvider,
        settings: Settings,
    ) -> None:
        self.documents = documents
        self.versions = versions
        self.projects = projects
        self.folders = folders
        self.users = users
        self.storage = storage
        self.settings = settings

    # ── 조회 ──

    def list_documents(
        self, project_id: int, *, folder_id=None, status=None, document_type=None
    ) -> list[Document]:
        self._ensure_project(project_id)
        return self.documents.list_by_project(
            project_id, folder_id=folder_id, status=status, document_type=document_type
        )

    def list_recent_documents(
        self, *, limit: int, project_id: int | None = None
    ) -> list[RecentDocumentRead]:
        """대시보드 최근 문서 카드용 — 프로젝트를 가로질러 최근 등록순"""
        if project_id is not None:
            self._ensure_project(project_id)
        return [
            RecentDocumentRead(
                id=row.id,
                name=row.name,
                project_id=row.project_id,
                project_name=row.project_name,
                processing_status=row.processing_status,
                created_at=row.created_at,
            )
            for row in self.documents.list_recent(limit=limit, project_id=project_id)
        ]

    def search_documents(self, q: str, *, limit: int) -> list[RecentDocumentRead]:
        """전역 검색창용 — 이름/설명 키워드로 프로젝트를 가로질러 검색"""
        q = q.strip()
        if not q:
            return []
        return [
            RecentDocumentRead(
                id=row.id,
                name=row.name,
                project_id=row.project_id,
                project_name=row.project_name,
                processing_status=row.processing_status,
                created_at=row.created_at,
            )
            for row in self.documents.search(q, limit=limit)
        ]

    def get_document(self, document_id: int) -> Document:
        doc = self.documents.get(document_id)
        if doc is None:
            raise DocumentNotFoundError(document_id)
        return doc

    # ── 작성자 이름 + 현재 버전을 채운 읽기 모델 ──

    def get_document_read(self, document_id: int) -> DocumentRead:
        doc = self.get_document(document_id)
        author_id = _author_id(doc.created_by)
        users = {u.id: u for u in self.users.get_many({author_id} if author_id else set())}
        versions = {
            v.id: v
            for v in self.versions.get_many(
                {doc.current_version_id} if doc.current_version_id else set()
            )
        }
        return self._build_read(doc, users, versions)

    def list_document_reads(
        self, project_id: int, *, folder_id=None, status=None, document_type=None
    ) -> list[DocumentRead]:
        docs = self.list_documents(
            project_id, folder_id=folder_id, status=status, document_type=document_type
        )
        author_ids = {aid for d in docs if (aid := _author_id(d.created_by)) is not None}
        version_ids = {d.current_version_id for d in docs if d.current_version_id}
        users = {u.id: u for u in self.users.get_many(author_ids)}
        versions = {v.id: v for v in self.versions.get_many(version_ids)}
        return [self._build_read(d, users, versions) for d in docs]

    def _build_read(self, doc: Document, users: dict, versions: dict) -> DocumentRead:
        author = None
        author_id = _author_id(doc.created_by)
        user = users.get(author_id) if author_id else None
        if user is not None:
            author = AuthorInfo(id=user.id, name=user.name, email=user.email)
        current_version = None
        if doc.current_version_id and doc.current_version_id in versions:
            current_version = DocumentVersionRead.model_validate(
                versions[doc.current_version_id]
            )
        read = DocumentRead.model_validate(doc)
        read.author = author
        read.current_version = current_version
        return read

    def list_versions(self, document_id: int) -> list[DocumentVersion]:
        self.get_document(document_id)
        return self.versions.list_by_document(document_id)

    def get_version(self, version_id: int) -> DocumentVersion:
        version = self.versions.get(version_id)
        if version is None:
            raise VersionNotFoundError(version_id)
        return version

    def list_sections(self, version_id: int):
        self.get_version(version_id)
        return self.versions.list_sections(version_id)

    def list_chunks(self, version_id: int):
        self.get_version(version_id)
        return self.versions.list_chunks(version_id)

    def resolve_download(self, document_id: int) -> tuple[DocumentVersion, Path]:
        doc = self.get_document(document_id)
        if doc.current_version_id is None:
            raise VersionNotFoundError(-1)
        version = self.get_version(doc.current_version_id)
        path = self.storage.resolve(version.storage_path)
        if not path.exists():
            raise VersionNotFoundError(version.id)
        return version, path

    # ── 업로드 ──

    def upload_document(
        self,
        project_id: int,
        *,
        folder_id: int | None,
        name: str | None,
        description: str | None,
        filename: str,
        content_type: str | None,
        data: bytes,
        created_by: str | None,
    ) -> tuple[Document, DocumentVersion]:
        self._ensure_project(project_id)
        if folder_id is not None:
            self._ensure_folder_in_project(project_id, folder_id)

        ext = self._validate_file(filename, data)

        document = self.documents.add(
            Document(
                project_id=project_id,
                folder_id=folder_id,
                name=name or filename,
                description=description,
                document_type=ext,
                created_by=created_by,
            )
        )

        version_no = 1
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        relative_dir = (
            f"documents/project-{project_id}/document-{document.id}/v{version_no}"
        )
        storage_path = self.storage.save(relative_dir, stored_name, data)

        version = self.versions.add(
            DocumentVersion(
                document_id=document.id,
                version_no=version_no,
                original_file_name=filename,
                storage_path=storage_path,
                mime_type=content_type,
                file_size=len(data),
                checksum=hashlib.sha256(data).hexdigest(),
                processing_status="UPLOADED",
            )
        )

        document.current_version_id = version.id
        self.documents.commit_refresh(document, version)
        return document, version

    def create_version(
        self,
        document_id: int,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> DocumentVersion:
        """기존 document 에 새 버전(v2+)을 추가한다. upload_document 와 달리 Document 는 새로 만들지 않는다."""
        document = self.get_document(document_id)
        existing = self.versions.list_by_document(document_id)  # version_no desc
        version_no = (existing[0].version_no + 1) if existing else 1

        ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
        stored_name = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
        relative_dir = (
            f"documents/project-{document.project_id}/document-{document.id}/v{version_no}"
        )
        storage_path = self.storage.save(relative_dir, stored_name, data)

        version = self.versions.add(
            DocumentVersion(
                document_id=document.id,
                version_no=version_no,
                original_file_name=filename,
                storage_path=storage_path,
                mime_type=content_type,
                file_size=len(data),
                checksum=hashlib.sha256(data).hexdigest(),
                processing_status="UPLOADED",
            )
        )

        document.current_version_id = version.id
        self.documents.commit_refresh(document, version)
        return version

    def delete_document(self, document_id: int) -> None:
        doc = self.get_document(document_id)
        relative_dir = f"documents/project-{doc.project_id}/document-{doc.id}"
        self.documents.delete(doc)  # DB (versions/sections/chunks cascade)
        self.storage.delete_dir(relative_dir)  # 파일 정리

    # ── 내부 헬퍼 ──

    def _ensure_project(self, project_id: int) -> None:
        if self.projects.get(project_id) is None:
            raise ProjectNotFoundError(project_id)

    def _ensure_folder_in_project(self, project_id: int, folder_id: int) -> None:
        folder = self.folders.get(folder_id)
        if folder is None or folder.project_id != project_id:
            raise DocumentValidationError("folder not found in this project")

    def _validate_file(self, filename: str, data: bytes) -> str:
        if "." not in filename:
            raise DocumentValidationError("파일 확장자가 없습니다")
        ext = filename.rsplit(".", 1)[1].lower()
        if ext not in self.settings.allowed_upload_extensions:
            raise DocumentValidationError(
                f"허용되지 않는 확장자: .{ext} "
                f"(허용: {', '.join(self.settings.allowed_upload_extensions)})"
            )
        if len(data) == 0:
            raise DocumentValidationError("빈 파일입니다")
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise DocumentValidationError(
                f"파일이 너무 큽니다 (최대 {self.settings.max_upload_mb}MB)"
            )
        return ext


def get_document_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentService:
    storage = LocalStorageProvider(settings.storage_root)
    return DocumentService(
        DocumentRepository(db),
        DocumentVersionRepository(db),
        ProjectRepository(db),
        FolderRepository(db),
        UserRepository(db),
        storage,
        settings,
    )
