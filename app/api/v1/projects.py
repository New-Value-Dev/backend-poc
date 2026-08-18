from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.activity_service import (
    Action,
    ActivityService,
    get_activity_service,
)
from app.services.project_service import (
    ProjectNotFoundError,
    ProjectService,
    get_project_service,
)

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectIdPath = Annotated[int, Path(description="프로젝트 id", examples=[1])]

# 인증이 걸린 모든 엔드포인트가 공유하는 오류 응답 설명.
AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
NOT_FOUND_RESPONSE = {404: {"description": "해당 프로젝트가 없음"}}


@router.get(
    "",
    response_model=list[ProjectRead],
    summary="프로젝트 목록",
    response_description="id 오름차순 전체 목록",
    responses=AUTH_RESPONSES,
)
def list_projects(
    service: ProjectService = Depends(get_project_service),
    _: User = Depends(get_current_user),
) -> list[ProjectRead]:
    """모든 프로젝트를 돌려준다. 아직 멤버십 필터링은 없어 로그인만 하면 전부 보인다"""
    return service.list_projects()


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="프로젝트 생성",
    response_description="생성된 프로젝트(201)",
    responses=AUTH_RESPONSES,
)
def create_project(
    payload: ProjectCreate,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    current_user: User = Depends(get_current_user),
) -> ProjectRead:
    """새 프로젝트를 만든다. created_by는 로그인 사용자 id로 서버가 채운다"""
    project = service.create_project(payload, created_by=str(current_user.id))
    activity.record(
        Action.PROJECT_CREATE,
        project_id=project.id,
        target_type="project",
        target_id=project.id,
        target_label=project.name,
    )
    return project


@router.get(
    "/{project_id}",
    response_model=ProjectRead,
    summary="프로젝트 상세",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def get_project(
    project_id: ProjectIdPath,
    service: ProjectService = Depends(get_project_service),
    _: User = Depends(get_current_user),
) -> ProjectRead:
    """프로젝트 하나를 조회한다."""
    try:
        return service.get_project(project_id)
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        ) from None


@router.patch(
    "/{project_id}",
    response_model=ProjectRead,
    summary="프로젝트 부분 수정",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def update_project(
    project_id: ProjectIdPath,
    payload: ProjectUpdate,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    _: User = Depends(get_current_user),
) -> ProjectRead:
    """이름·설명을 부분 수정한다. 보낸 필드만 반영되고 생략한 필드는 기존 값을 유지한다"""
    try:
        project = service.update_project(project_id, payload)
        activity.record(
            Action.PROJECT_UPDATE,
            project_id=project.id,
            target_type="project",
            target_id=project.id,
            target_label=project.name,
            meta={"changed": sorted(payload.model_dump(exclude_unset=True))},
        )
        return project
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        ) from None


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="프로젝트 삭제",
    response_description="본문 없음(204)",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def delete_project(
    project_id: ProjectIdPath,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    _: User = Depends(get_current_user),
) -> None:
    """프로젝트를 삭제한다. 소속 폴더·문서·버전·섹션·청크가 CASCADE로 함께 지워지며 되돌릴 수 없다"""
    try:
        # 지우고 나면 이름을 읽을 수 없으므로 로그용으로 먼저 확보한다.
        name = service.get_project(project_id).name
        service.delete_project(project_id)
        activity.record(
            Action.PROJECT_DELETE,
            project_id=project_id,
            target_type="project",
            target_id=project_id,
            target_label=name,
        )
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        ) from None
