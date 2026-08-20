from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.mypage import MyPageSummary
from app.services.mypage_service import MyPageService, get_mypage_service

router = APIRouter(tags=["mypage"])

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}


@router.get(
    "/mypage/summary",
    response_model=MyPageSummary,
    summary="마이페이지 집계",
    response_description="내 프로필 + 내가 만든 프로젝트/문서 수 + 내 최근 활동",
    responses=AUTH_RESPONSES,
)
def get_mypage_summary(
    activity_limit: Annotated[
        int, Query(ge=1, le=100, description="최근 활동 최대 건수")
    ] = 10,
    service: MyPageService = Depends(get_mypage_service),
    user: User = Depends(get_current_user),
) -> MyPageSummary:
    """/dashboard/summary, /activity 와 달리 project_id 가 아니라 로그인 사용자
    (created_by/actor_id) 기준으로 스코핑된 집계."""
    return service.get_summary(user, activity_limit=activity_limit)
