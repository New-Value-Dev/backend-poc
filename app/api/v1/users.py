from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserSearchResult
from app.services.project_service import (
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectService,
    get_project_service,
)
from app.services.user_service import SEARCH_MIN_LENGTH, UserService, get_user_service

router = APIRouter(prefix="/users", tags=["users"])

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}


@router.get(
    "/search",
    response_model=list[UserSearchResult],
    summary="사용자 검색 (멤버 초대용)",
    response_description="이름/이메일 부분일치 사용자 (앞부분 일치 우선, 최대 limit 건)",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "exclude_project_id 프로젝트가 없음"},
        403: {"description": "exclude_project_id 프로젝트에 접근 권한이 없음"},
    },
)
def search_users(
    q: Annotated[
        str,
        Query(
            min_length=SEARCH_MIN_LENGTH,
            max_length=320,
            description="이름 또는 이메일 일부 (대소문자 무시, 최소 2자)",
            examples=["kim"],
        ),
    ],
    limit: Annotated[int, Query(ge=1, le=50, description="최대 결과 수")] = 20,
    exclude_project_id: Annotated[
        int | None,
        Query(
            description="이 프로젝트의 기존 멤버·초대 대기자를 결과에서 제외 (초대 화면에서 사용)"
        ),
    ] = None,
    service: UserService = Depends(get_user_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> list[UserSearchResult]:
    """가입된 사용자를 이름/이메일로 검색"""
    if exclude_project_id is not None:
        # 멤버 목록을 간접적으로 흘리지 않도록, 그 프로젝트를 볼 수 있는 사람만 필터를 쓸 수 있다.
        try:
            projects.check_access(exclude_project_id, current_user)
        except ProjectNotFoundError:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Project {exclude_project_id} not found"
            ) from None
        except ProjectForbiddenError:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "이 프로젝트에 접근할 권한이 없습니다"
            ) from None
    return [
        UserSearchResult.model_validate(user)
        for user in service.search(q, limit=limit, exclude_project_id=exclude_project_id)
    ]
