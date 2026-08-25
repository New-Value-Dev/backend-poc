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

from app.api.deps import get_current_user, require_project_access
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.project import Project
from app.models.user import User
from app.schemas.diff import DiffResult
from app.schemas.document import (
    ChunkRead,
    DocumentMove,
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
from app.services.diff_service import DiffService, get_diff_service
from app.services.document_service import (
    DocumentNotFoundError,
    DocumentService,
    DocumentValidationError,
    VersionNotFoundError,
    get_document_service,
    status_progress,
)
from app.services.parsing_service import run_parse_task
from app.services.project_service import (
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectService,
    get_project_service,
)

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
FORBIDDEN_RESPONSE = {403: {"description": "이 문서가 속한 프로젝트에 접근할 권한이 없음"}}


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def _check_access(
    project_id: int, projects: ProjectService, current_user: User, not_found_message: str
) -> None:
    try:
        projects.check_access(project_id, current_user)
    except ProjectForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "이 문서에 접근할 권한이 없습니다"
        ) from None
    except ProjectNotFoundError:
        raise _not_found(not_found_message) from None


def check_document_access(
    document_id: DocumentIdPath,
    service: DocumentService = Depends(get_document_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> Document:
    """document_id 만 경로에 있는 라우트용 — document → project 를 거슬러 올라가 접근을 확인한다"""
    try:
        doc = service.get_document(document_id)
    except DocumentNotFoundError:
        raise _not_found(f"Document {document_id} not found") from None
    _check_access(doc.project_id, projects, current_user, f"Document {document_id} not found")
    return doc


def check_version_access(
    version_id: VersionIdPath,
    service: DocumentService = Depends(get_document_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> DocumentVersion:
    """version_id 만 경로에 있는 라우트용 — version → document → project 순으로 접근을 확인한다"""
    try:
        version = service.get_version(version_id)
    except VersionNotFoundError:
        raise _not_found(f"Version {version_id} not found") from None
    doc = service.get_document(version.document_id)
    _check_access(doc.project_id, projects, current_user, f"Version {version_id} not found")
    return version


@router.get(
    "/projects/{project_id}/documents",
    response_model=list[DocumentRead],
    summary="문서 목록",
    response_description="최근 등록순 문서 목록(작성자·현재 버전 포함)",
    responses={**AUTH_RESPONSES, 404: {"description": "프로젝트 없음"}, **FORBIDDEN_RESPONSE},
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
    _: Project = Depends(require_project_access),
) -> list[DocumentRead]:
    """프로젝트의 문서 목록을 돌려준다"""
    return service.list_document_reads(
        project_id,
        folder_id=folder_id,
        status=status_filter.value if status_filter else None,
        document_type=type,
    )


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
        **FORBIDDEN_RESPONSE,
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
    _: Project = Depends(require_project_access),
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
    # document 는 아직 author 가 채워지지 않은 ORM 객체이므로, 목록/상세와 동일하게
    # 조회 경로를 다시 태워 author(작성자 이름)를 채운 뒤 응답한다.
    document_read = service.get_document_read(document.id)
    return DocumentUploadResponse(document=document_read, version=version)


@router.get(
    "/documents/recent",
    response_model=list[RecentDocumentRead],
    summary="최근 문서 (프로젝트 교차)",
    response_description="등록 최신순. 프로젝트 이름과 현재 처리 상태가 함께 온다",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "project_id 로 지정한 프로젝트 없음"},
        **FORBIDDEN_RESPONSE,
    },
)
def list_recent_documents(
    limit: Annotated[int, Query(ge=1, le=50, description="가져올 최대 건수")] = 5,
    project_id: Annotated[
        int | None,
        Query(description="지정 시 해당 프로젝트만. 생략하면 전체 프로젝트를 가로질러 조회"),
    ] = None,
    service: DocumentService = Depends(get_document_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> list[RecentDocumentRead]:
    """대시보드 최근 문서 카드에 쓰는 최근 문서 목록을 돌려준다"""
    accessible_ids = None
    if project_id is not None:
        _check_access(project_id, projects, current_user, f"Project {project_id} not found")
    else:
        accessible_ids = projects.accessible_project_ids_for(current_user)
    return service.list_recent_documents(
        limit=limit, project_id=project_id, accessible_project_ids=accessible_ids
    )


@router.get(
    "/documents/search",
    response_model=list[RecentDocumentRead],
    summary="문서 검색 (프로젝트 교차)",
    response_description="이름·설명에 키워드가 포함된 문서를 최신순으로",
    responses=AUTH_RESPONSES,
)
def search_documents(
    q: Annotated[str, Query(min_length=1, description="검색어. 문서 이름/설명에서 찾는다")],
    limit: Annotated[int, Query(ge=1, le=50, description="가져올 최대 건수")] = 20,
    service: DocumentService = Depends(get_document_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> list[RecentDocumentRead]:
    """전역 검색창(문서 검색)용. `/documents/recent`와 응답 shape은 같지만 최신순이 아니라
    키워드 매칭 기준이다."""
    accessible_ids = projects.accessible_project_ids_for(current_user)
    return service.search_documents(q, limit=limit, accessible_project_ids=accessible_ids)


@router.get(
    "/documents/{document_id}",
    response_model=DocumentRead,
    summary="문서 상세",
    response_description="문서 + `author` + `current_version`",
    responses={**AUTH_RESPONSES, 404: {"description": "문서 없음"}, **FORBIDDEN_RESPONSE},
)
def get_document(
    service: DocumentService = Depends(get_document_service),
    doc: Document = Depends(check_document_access),
) -> DocumentRead:
    """문서 하나를 조회한다"""
    return service.get_document_read(doc.id)


@router.get(
    "/documents/{document_id}/versions",
    response_model=list[DocumentVersionRead],
    summary="버전 목록",
    response_description="version_no 내림차순(최신 우선)",
    responses={**AUTH_RESPONSES, 404: {"description": "문서 없음"}, **FORBIDDEN_RESPONSE},
)
def list_versions(
    service: DocumentService = Depends(get_document_service),
    doc: Document = Depends(check_document_access),
) -> list[DocumentVersionRead]:
    """문서의 모든 버전을 최신순으로 돌려준다"""
    return service.list_versions(doc.id)


@router.get(
    "/documents/{document_id}/diff",
    response_model=DiffResult,
    summary="버전 비교",
    response_description="섹션 단위 added/deleted/modified/unchanged + 토큰 단위 diff",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "버전이 없거나 이 문서 소속이 아님"},
        **FORBIDDEN_RESPONSE,
    },
)
def get_document_diff(
    from_version_id: Annotated[int, Query(description="비교 기준(이전) 버전 id")],
    to_version_id: Annotated[int, Query(description="비교 대상(이후) 버전 id")],
    service: DiffService = Depends(get_diff_service),
    doc: Document = Depends(check_document_access),
) -> DiffResult:
    """두 버전의 섹션을 정렬해 비교한다. 검색이 아니라 이미 정해진 두 버전만 비교하는
    문제라 임베딩/LLM 없이 동기로 즉시 계산해 돌려준다. `tokens`를 순서대로 이어붙이면
    git diff처럼 삭제/추가/유지 구간을 그대로 렌더링할 수 있다."""
    try:
        return service.get_diff(doc.id, from_version_id, to_version_id)
    except VersionNotFoundError as exc:
        raise _not_found(f"Version {exc.version_id} not found or not in this document") from None


@router.get(
    "/documents/{document_id}/download",
    summary="원본 파일 다운로드",
    response_description="업로드 당시 파일명·MIME 으로 내려주는 원본 바이트",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "문서가 없거나 저장된 파일이 없음"},
        **FORBIDDEN_RESPONSE,
    },
)
def download_document(
    service: DocumentService = Depends(get_document_service),
    doc: Document = Depends(check_document_access),
) -> FileResponse:
    """현재 버전의 원본 파일을 그대로 내려준다. 파싱 결과가 아니라 업로드했던 원본 바이트다"""
    try:
        version, path = service.resolve_download(doc.id)
    except VersionNotFoundError:
        raise _not_found("No stored file for this document") from None
    return FileResponse(
        path,
        filename=version.original_file_name,
        media_type=version.mime_type or "application/octet-stream",
        # 이 URL은 버전이 바뀌어도(v1→v2) 그대로라, 캐시 기본값에 맡기면 브라우저가
        # 교정 적용 후에도 예전 버전을 재요청 없이 그대로 보여줄 수 있다.
        headers={"Cache-Control": "no-store"},
    )


@router.patch(
    "/documents/{document_id}/move",
    response_model=DocumentRead,
    summary="문서 이동 / 폴더 변경",
    response_description="이동/폴더 변경된 문서(현재 프로젝트·폴더가 반영됨)",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "대상 folder_id가 대상 프로젝트 소속이 아님"},
        404: {"description": "문서 또는 (project_id 지정 시) 대상 프로젝트 없음"},
        403: {"description": "원본 또는 (project_id 지정 시) 대상 프로젝트에 접근 권한이 없음"},
    },
)
def move_document(
    payload: DocumentMove,
    service: DocumentService = Depends(get_document_service),
    projects: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    current_user: User = Depends(get_current_user),
    doc: Document = Depends(check_document_access),
) -> DocumentRead:
    """개인 프로젝트에서 다듬은 문서를 완성 후 다른 프로젝트로 옮길 때 / 같은 프로젝트 안에서 folder_id만 바꿀 때 (project_id 생략)"""
    target_project_id = payload.project_id
    if target_project_id is not None:
        _check_access(
            target_project_id, projects, current_user, f"Project {target_project_id} not found"
        )
    from_project_id = doc.project_id
    from_folder_id = doc.folder_id
    try:
        moved = service.move_document(
            doc.id, project_id=target_project_id, folder_id=payload.folder_id
        )
    except DocumentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    if target_project_id is not None and target_project_id != from_project_id:
        activity.record(
            Action.DOCUMENT_MOVE,
            project_id=moved.project_id,
            target_type="document",
            target_id=moved.id,
            target_label=moved.name,
            meta={"from_project_id": from_project_id, "to_project_id": moved.project_id},
        )
    else:
        activity.record(
            Action.DOCUMENT_FOLDER_CHANGE,
            project_id=moved.project_id,
            target_type="document",
            target_id=moved.id,
            target_label=moved.name,
            meta={"from_folder_id": from_folder_id, "to_folder_id": moved.folder_id},
        )
    return service.get_document_read(moved.id)


@router.get(
    "/versions/{version_id}",
    response_model=DocumentVersionRead,
    summary="버전 상세",
    responses={**AUTH_RESPONSES, 404: {"description": "버전 없음"}, **FORBIDDEN_RESPONSE},
)
def get_version(
    version: DocumentVersion = Depends(check_version_access),
) -> DocumentVersionRead:
    """버전 하나의 메타데이터를 조회한다"""
    return version


@router.get(
    "/versions/{version_id}/status",
    response_model=VersionStatusResponse,
    summary="처리 상태 폴링",
    response_description="`{version_id, status, progress}` — progress 는 0~100",
    responses={**AUTH_RESPONSES, 404: {"description": "버전 없음"}, **FORBIDDEN_RESPONSE},
)
def get_version_status(
    version: DocumentVersion = Depends(check_version_access),
) -> VersionStatusResponse:
    """업로드 후 파싱·청킹 진행 상황을 확인한다"""
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
    responses={**AUTH_RESPONSES, 404: {"description": "버전 없음"}, **FORBIDDEN_RESPONSE},
)
def list_sections(
    service: DocumentService = Depends(get_document_service),
    version: DocumentVersion = Depends(check_version_access),
) -> list[SectionRead]:
    """파서가 만든 섹션을 문서 순서대로 돌려준다"""
    return service.list_sections(version.id)


@router.get(
    "/versions/{version_id}/chunks",
    response_model=list[ChunkRead],
    summary="청크 목록",
    response_description="`chunk_index` 오름차순",
    responses={**AUTH_RESPONSES, 404: {"description": "버전 없음"}, **FORBIDDEN_RESPONSE},
)
def list_chunks(
    service: DocumentService = Depends(get_document_service),
    version: DocumentVersion = Depends(check_version_access),
) -> list[ChunkRead]:
    """임베딩·검색의 최소 단위인 청크를 돌려준다"""
    return service.list_chunks(version.id)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="문서 삭제",
    response_description="본문 없음(204)",
    responses={**AUTH_RESPONSES, 404: {"description": "문서 없음"}, **FORBIDDEN_RESPONSE},
)
def delete_document(
    service: DocumentService = Depends(get_document_service),
    activity: ActivityService = Depends(get_activity_service),
    doc: Document = Depends(check_document_access),
) -> None:
    """문서를 삭제한다"""
    project_id, document_id, name = doc.project_id, doc.id, doc.name
    service.delete_document(document_id)
    activity.record(
        Action.DOCUMENT_DELETE,
        project_id=project_id,
        target_type="document",
        target_id=document_id,
        target_label=name,
    )
