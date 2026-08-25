from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.deps import get_current_user, require_project_access
from app.models.folder import Folder
from app.models.project import Project
from app.models.user import User
from app.schemas.folder import FolderCreate, FolderRead, FolderReorder, FolderUpdate
from app.services.activity_service import (
    Action,
    ActivityService,
    get_activity_service,
)
from app.services.folder_service import (
    FolderNotFoundError,
    FolderService,
    FolderValidationError,
    get_folder_service,
)
from app.services.project_service import (
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectService,
    get_project_service,
)

router = APIRouter(tags=["folders"])

ProjectIdPath = Annotated[int, Path(description="폴더가 속한 프로젝트 id", examples=[1])]
FolderIdPath = Annotated[int, Path(description="폴더 id", examples=[1])]

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
FORBIDDEN_RESPONSE = {403: {"description": "이 폴더가 속한 프로젝트에 접근할 권한이 없음"}}


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def check_folder_access(
    folder_id: FolderIdPath,
    folders: FolderService = Depends(get_folder_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> Folder:
    """folder_id 만 경로에 있는 라우트용"""
    try:
        folder = folders.get_folder(folder_id)
    except FolderNotFoundError:
        raise _not_found(f"Folder {folder_id} not found") from None
    try:
        projects.check_access(folder.project_id, current_user)
    except ProjectForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "이 폴더에 접근할 권한이 없습니다"
        ) from None
    except ProjectNotFoundError:
        raise _not_found(f"Folder {folder_id} not found") from None
    return folder


@router.get(
    "/projects/{project_id}/folders",
    response_model=list[FolderRead],
    summary="폴더 목록(트리 구성용)",
    response_description="해당 프로젝트의 전체 폴더를 평탄한 배열로",
    responses={**AUTH_RESPONSES, 404: {"description": "프로젝트 없음"}, **FORBIDDEN_RESPONSE},
)
def list_folders(
    project_id: ProjectIdPath,
    service: FolderService = Depends(get_folder_service),
    _: Project = Depends(require_project_access),
) -> list[FolderRead]:
    """프로젝트의 모든 폴더를 평탄한 목록으로 돌려준다"""
    return service.list_folders(project_id)


@router.post(
    "/projects/{project_id}/folders",
    response_model=FolderRead,
    status_code=status.HTTP_201_CREATED,
    summary="폴더 생성",
    response_description="생성된 폴더(201)",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "parent_id 가 없거나 다른 프로젝트 소속"},
        404: {"description": "프로젝트 없음"},
        **FORBIDDEN_RESPONSE,
    },
)
def create_folder(
    project_id: ProjectIdPath,
    payload: FolderCreate,
    service: FolderService = Depends(get_folder_service),
    activity: ActivityService = Depends(get_activity_service),
    _: Project = Depends(require_project_access),
) -> FolderRead:
    """폴더를 만든다. parent_id를 주면 그 아래 하위 폴더로, 생략하면 최상위로 생성된다"""
    try:
        folder = service.create_folder(project_id, payload)
    except FolderValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    activity.record(
        Action.FOLDER_CREATE,
        project_id=project_id,
        target_type="folder",
        target_id=folder.id,
        target_label=folder.name,
    )
    return folder


@router.patch(
    "/folders/{folder_id}",
    response_model=FolderRead,
    summary="폴더 이름 변경 / 이동",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "이동 대상이 잘못됨(자기 자신·자손으로 이동 등 순환 발생)"},
        404: {"description": "폴더 없음"},
        **FORBIDDEN_RESPONSE,
    },
)
def update_folder(
    payload: FolderUpdate,
    service: FolderService = Depends(get_folder_service),
    activity: ActivityService = Depends(get_activity_service),
    folder: Folder = Depends(check_folder_access),
) -> FolderRead:
    """이름을 바꾸거나 parent_id로 다른 폴더 아래로 옮긴다. 순환 이동은 400으로 막는다"""
    try:
        updated = service.update_folder(folder.id, payload)
    except FolderValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    activity.record(
        Action.FOLDER_UPDATE,
        project_id=updated.project_id,
        target_type="folder",
        target_id=updated.id,
        target_label=updated.name,
        meta={"changed": sorted(payload.model_dump(exclude_unset=True))},
    )
    return updated


@router.patch(
    "/folders/{folder_id}/reorder",
    response_model=list[FolderRead],
    summary="폴더 순서 변경",
    response_description="영향받은 형제 폴더 목록(새 순서 반영)",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "이동 대상이 잘못됨(자기 자신·자손으로 이동 등 순환 발생)"},
        404: {"description": "폴더 없음"},
        **FORBIDDEN_RESPONSE,
    },
)
def reorder_folder(
    payload: FolderReorder,
    service: FolderService = Depends(get_folder_service),
    activity: ActivityService = Depends(get_activity_service),
    folder: Folder = Depends(check_folder_access),
) -> list[FolderRead]:
    """target_index 위치로 순서를 옮긴다. parent_id를 함께 주면 다른 폴더 아래로 이동하면서 순서도 정한다"""
    project_id, folder_id, name = folder.project_id, folder.id, folder.name
    try:
        siblings = service.reorder_folder(folder_id, payload)
    except FolderValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    activity.record(
        Action.FOLDER_UPDATE,
        project_id=project_id,
        target_type="folder",
        target_id=folder_id,
        target_label=name,
        meta={"reordered": True},
    )
    return siblings


@router.delete(
    "/folders/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="폴더 삭제",
    response_description="본문 없음(204)",
    responses={**AUTH_RESPONSES, 404: {"description": "폴더 없음"}, **FORBIDDEN_RESPONSE},
)
def delete_folder(
    service: FolderService = Depends(get_folder_service),
    activity: ActivityService = Depends(get_activity_service),
    folder: Folder = Depends(check_folder_access),
) -> None:
    """폴더를 삭제한다. 하위 폴더는 함께 지워지지만 문서는 folder_id가 null이 되어 프로젝트 최상위로 올라온다"""
    project_id, folder_id, name = folder.project_id, folder.id, folder.name
    service.delete_folder(folder_id)
    activity.record(
        Action.FOLDER_DELETE,
        project_id=project_id,
        target_type="folder",
        target_id=folder_id,
        target_label=name,
    )
