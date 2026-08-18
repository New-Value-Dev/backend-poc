from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.dashboard import ActivityItem, DashboardSummary
from app.services.dashboard_service import DashboardService, get_dashboard_service
from app.services.project_service import ProjectNotFoundError

router = APIRouter(tags=["dashboard"])

ProjectScopeQuery = Annotated[
    int | None,
    Query(
        description="지정 시 해당 프로젝트만 집계. 생략하면 전체. 없는 id 면 404",
        examples=[1],
    ),
]

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
SCOPE_RESPONSES = {
    **AUTH_RESPONSES,
    404: {"description": "project_id 로 지정한 프로젝트 없음"},
}


def _not_found(project_id: int | None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_id} not found"
    )


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummary,
    summary="대시보드 집계",
    response_description="스탯 4종 + 주간 처리량 + 문서 유형 분포 + 파이프라인 카운트",
    responses=SCOPE_RESPONSES,
)
def get_dashboard_summary(
    project_id: ProjectScopeQuery = None,
    service: DashboardService = Depends(get_dashboard_service),
    _: User = Depends(get_current_user),
) -> DashboardSummary:
    """홈 대시보드 집계를 돌려준다"""
    try:
        return service.get_summary(project_id=project_id)
    except ProjectNotFoundError:
        raise _not_found(project_id) from None


@router.get(
    "/activity",
    response_model=list[ActivityItem],
    summary="최근 활동 피드",
    response_description="최신순 활동 목록",
    responses=SCOPE_RESPONSES,
)
def list_activity(
    limit: Annotated[
        int, Query(ge=1, le=100, description="가져올 최대 건수")
    ] = 10,
    project_id: ProjectScopeQuery = None,
    action: Annotated[
        str | None,
        Query(
            description=(
                "액션 코드로 정확히 거른다. `auth.login` · `project.create|update|delete` · "
                "`folder.create|update|delete` · `document.upload|delete` · "
                "`analysis.start|complete|fail`"
            ),
            examples=["document.upload"],
        ),
    ] = None,
    service: DashboardService = Depends(get_dashboard_service),
    _: User = Depends(get_current_user),
) -> list[ActivityItem]:
    """최근 활동을 최신순으로 돌려준다"""
    try:
        return service.get_activity(limit=limit, project_id=project_id, action=action)
    except ProjectNotFoundError:
        raise _not_found(project_id) from None
