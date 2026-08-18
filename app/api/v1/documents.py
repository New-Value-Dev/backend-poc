from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.document import (
    ChunkRead,
    DocumentRead,
    DocumentUploadResponse,
    DocumentVersionRead,
    ProcessingStatus,
    RecentDocumentRead,
    SectionRead,
    VersionStatusResponse,
)
from app.services.activity_service import (
    Action,
    ActivityService,
    get_activity_service,
)
from app.services.document_service import (
    DocumentNotFoundError,
    DocumentService,
    DocumentValidationError,
    VersionNotFoundError,
    get_document_service,
    status_progress,
)
from app.services.parsing_service import run_parse_task
from app.services.project_service import ProjectNotFoundError

router = APIRouter(tags=["documents"])

ProjectIdPath = Annotated[int, Path(description="프로젝트 id", examples=[1])]
DocumentIdPath = Annotated[int, Path(description="문서 id", examples=[1])]
VersionIdPath = Annotated[
    int,
    Path(
        description="문서 버전 id (문서 id 가 아니다 — `current_version.id` 를 쓸 것)",
        examples=[1],
    ),
]

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


@router.get(
    "/projects/{project_id}/documents",
    response_model=list[DocumentRead],
    summary="문서 목록",
    response_description="최근 등록순 문서 목록(작성자·현재 버전 포함)",
    responses={**AUTH_RESPONSES, 404: {"description": "프로젝트 없음"}},
)
def list_documents(
    project_id: ProjectIdPath,
    folder_id: Annotated[
        int | None,
        Query(description="지정 시 해당 폴더 직속 문서만. 생략하면 프로젝트 전체(하위 폴더 포함)"),
    ] = None,
    status_filter: Annotated[
        ProcessingStatus | None,
        Query(
            alias="status",
            description=(
                "**현재 버전의 처리 상태**로 거른다(문서 생명주기 `documents.status` 가 아님). "
                "현재 버전이 없는 문서는 제외된다."
            ),
        ),
    ] = None,
    type: Annotated[
        str | None,
        Query(description="`document_type` 정확 일치. 예: `pdf`, `RULE`", examples=["pdf"]),
    ] = None,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> list[DocumentRead]:
    """프로젝트의 문서 목록을 돌려준다"""
    try:
        return service.list_document_reads(
            project_id,
            folder_id=folder_id,
            status=status_filter.value if status_filter else None,
            document_type=type,
        )
    except ProjectNotFoundError:
        raise _not_found(f"Project {project_id} not found") from None


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="문서 업로드 (멀티파트)",
    response_description="생성된 문서 + v1 버전(202). 파싱은 아직 진행 중이다",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "지원하지 않는 확장자, 용량 초과, 또는 folder_id 가 잘못됨"},
        404: {"description": "프로젝트 없음"},
    },
)
async def upload_document(
    project_id: ProjectIdPath,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="업로드할 원본 파일")],
    folder_id: Annotated[
        int | None, Form(description="넣을 폴더 id. 생략하면 프로젝트 최상위")
    ] = None,
    name: Annotated[
        str | None, Form(description="표시용 문서 이름. 생략하면 업로드 파일명을 쓴다")
    ] = None,
    description: Annotated[str | None, Form(description="문서 설명(선택)")] = None,
    service: DocumentService = Depends(get_document_service),
    activity: ActivityService = Depends(get_activity_service),
    current_user: User = Depends(get_current_user),
) -> DocumentUploadResponse:
    """파일을 저장하고 문서 + v1 버전을 만든 뒤 즉시 202를 반환한다. 이후 백그라운드에서 파싱과 청킹이 진행되며 상태는 버전 상태 조회로 폴링해 확인한다"""
    data = await file.read()
    try:
        document, version = service.upload_document(
            project_id,
            folder_id=folder_id,
            name=name,
            description=description,
            filename=file.filename or "unnamed",
            content_type=file.content_type,
            data=data,
            created_by=str(current_user.id),
        )
    except ProjectNotFoundError:
        raise _not_found(f"Project {project_id} not found") from None
    except DocumentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    activity.record(
        Action.DOCUMENT_UPLOAD,
        project_id=project_id,
        target_type="document",
        target_id=document.id,
        target_label=version.original_file_name,
        meta={"version_no": version.version_no, "file_size": version.file_size},
    )

    background_tasks.add_task(run_parse_task, version.id)
    return DocumentUploadResponse(document=document, version=version)


@router.get(
    "/documents/recent",
    response_model=list[RecentDocumentRead],
    summary="최근 문서 (프로젝트 교차)",
    response_description="등록 최신순. 프로젝트 이름과 현재 처리 상태가 함께 온다",
    responses={**AUTH_RESPONSES, 404: {"description": "project_id 로 지정한 프로젝트 없음"}},
)
def list_recent_documents(
    limit: Annotated[int, Query(ge=1, le=50, description="가져올 최대 건수")] = 5,
    project_id: Annotated[
        int | None,
        Query(description="지정 시 해당 프로젝트만. 생략하면 전체 프로젝트를 가로질러 조회"),
    ] = None,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> list[RecentDocumentRead]:
    """대시보드 최근 문서 카드에 쓰는 최근 문서 목록을 돌려준다"""
    try:
        return service.list_recent_documents(limit=limit, project_id=project_id)
    except ProjectNotFoundError:
        raise _not_found(f"Project {project_id} not found") from None


@router.get(
    "/documents/{document_id}",
    response_model=DocumentRead,
    summary="문서 상세",
    response_description="문서 + `author` + `current_version`",
    responses={**AUTH_RESPONSES, 404: {"description": "문서 없음"}},
)
def get_document(
    document_id: DocumentIdPath,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> DocumentRead:
    """문서 하나를 조회한다"""
    try:
        return service.get_document_read(document_id)
    except DocumentNotFoundError:
        raise _not_found(f"Document {document_id} not found") from None


@router.get(
    "/documents/{document_id}/versions",
    response_model=list[DocumentVersionRead],
    summary="버전 목록",
    response_description="version_no 내림차순(최신 우선)",
    responses={**AUTH_RESPONSES, 404: {"description": "문서 없음"}},
)
def list_versions(
    document_id: DocumentIdPath,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> list[DocumentVersionRead]:
    """문서의 모든 버전을 최신순으로 돌려준다"""
    try:
        return service.list_versions(document_id)
    except DocumentNotFoundError:
        raise _not_found(f"Document {document_id} not found") from None


@router.get(
    "/documents/{document_id}/download",
    summary="원본 파일 다운로드",
    response_description="업로드 당시 파일명·MIME 으로 내려주는 원본 바이트",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "문서가 없거나 저장된 파일이 없음"},
    },
)
def download_document(
    document_id: DocumentIdPath,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> FileResponse:
    """현재 버전의 원본 파일을 그대로 내려준다. 파싱 결과가 아니라 업로드했던 원본 바이트다"""
    try:
        version, path = service.resolve_download(document_id)
    except DocumentNotFoundError:
        raise _not_found(f"Document {document_id} not found") from None
    except VersionNotFoundError:
        raise _not_found("No stored file for this document") from None
    return FileResponse(
        path,
        filename=version.original_file_name,
        media_type=version.mime_type or "application/octet-stream",
    )


@router.get(
    "/versions/{version_id}",
    response_model=DocumentVersionRead,
    summary="버전 상세",
    responses={**AUTH_RESPONSES, 404: {"description": "버전 없음"}},
)
def get_version(
    version_id: VersionIdPath,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> DocumentVersionRead:
    """버전 하나의 메타데이터를 조회한다"""
    try:
        return service.get_version(version_id)
    except VersionNotFoundError:
        raise _not_found(f"Version {version_id} not found") from None


@router.get(
    "/versions/{version_id}/status",
    response_model=VersionStatusResponse,
    summary="처리 상태 폴링",
    response_description="`{version_id, status, progress}` — progress 는 0~100",
    responses={**AUTH_RESPONSES, 404: {"description": "버전 없음"}},
)
def get_version_status(
    version_id: VersionIdPath,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> VersionStatusResponse:
    """업로드 후 파싱·청킹 진행 상황을 확인한다"""
    try:
        version = service.get_version(version_id)
    except VersionNotFoundError:
        raise _not_found(f"Version {version_id} not found") from None
    return VersionStatusResponse(
        version_id=version.id,
        status=version.processing_status,
        progress=status_progress(version.processing_status),
    )


@router.get(
    "/versions/{version_id}/sections",
    response_model=list[SectionRead],
    summary="파싱된 섹션 목록",
    response_description="`order_no` 오름차순(문서 등장 순서)",
    responses={**AUTH_RESPONSES, 404: {"description": "버전 없음"}},
)
def list_sections(
    version_id: VersionIdPath,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> list[SectionRead]:
    """파서가 만든 섹션을 문서 순서대로 돌려준다"""
    try:
        return service.list_sections(version_id)
    except VersionNotFoundError:
        raise _not_found(f"Version {version_id} not found") from None


@router.get(
    "/versions/{version_id}/chunks",
    response_model=list[ChunkRead],
    summary="청크 목록",
    response_description="`chunk_index` 오름차순",
    responses={**AUTH_RESPONSES, 404: {"description": "버전 없음"}},
)
def list_chunks(
    version_id: VersionIdPath,
    service: DocumentService = Depends(get_document_service),
    _: User = Depends(get_current_user),
) -> list[ChunkRead]:
    """임베딩·검색의 최소 단위인 청크를 돌려준다"""
    try:
        return service.list_chunks(version_id)
    except VersionNotFoundError:
        raise _not_found(f"Version {version_id} not found") from None


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="문서 삭제",
    response_description="본문 없음(204)",
    responses={**AUTH_RESPONSES, 404: {"description": "문서 없음"}},
)
def delete_document(
    document_id: DocumentIdPath,
    service: DocumentService = Depends(get_document_service),
    activity: ActivityService = Depends(get_activity_service),
    _: User = Depends(get_current_user),
) -> None:
    """문서를 삭제한다"""
    try:
        doc = service.get_document(document_id)
        project_id, name = doc.project_id, doc.name
        service.delete_document(document_id)
        activity.record(
            Action.DOCUMENT_DELETE,
            project_id=project_id,
            target_type="document",
            target_id=document_id,
            target_label=name,
        )
    except DocumentNotFoundError:
        raise _not_found(f"Document {document_id} not found") from None
