from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.notification import (
    NotificationListResponse,
    NotificationRead,
    UnreadCountResponse,
)
from app.services.notification_service import (
    NotificationNotFoundError,
    NotificationService,
    get_notification_service,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
NOT_FOUND_RESPONSE = {404: {"description": "내 알림 중에 해당 id 가 없음"}}

NotificationIdPath = Annotated[int, Path(description="알림 id", examples=[1])]


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="내 알림 목록",
    response_description="최신순 알림 + 전체 미읽음 수",
    responses=AUTH_RESPONSES,
)
def list_notifications(
    only_unread: Annotated[
        bool, Query(description="true 면 안 읽은 알림만")
    ] = False,
    limit: Annotated[int, Query(ge=1, le=100, description="최대 건수")] = 20,
    offset: Annotated[int, Query(ge=0, description="건너뛸 건수(페이지네이션)")] = 0,
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
) -> NotificationListResponse:
    """로그인 사용자에게 온 알림만"""
    items, unread = service.list_for_user(
        current_user, only_unread=only_unread, limit=limit, offset=offset
    )
    return NotificationListResponse(
        items=[NotificationRead.model_validate(item) for item in items], unread=unread
    )


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="안 읽은 알림 수",
    responses=AUTH_RESPONSES,
)
def get_unread_count(
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
) -> UnreadCountResponse:
    """목록 없이 뱃지 숫자만 폴링할 때"""
    return UnreadCountResponse(unread=service.unread_count(current_user))


@router.post(
    "/read-all",
    response_model=UnreadCountResponse,
    summary="알림 전체 읽음 처리",
    response_description="처리 후 미읽음 수(항상 0)",
    responses=AUTH_RESPONSES,
)
def mark_all_read(
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
) -> UnreadCountResponse:
    service.mark_all_read(current_user)
    return UnreadCountResponse(unread=0)


@router.post(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="알림 하나 읽음 처리",
    response_description="읽음 처리된 알림(read_at 채워짐)",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def mark_read(
    notification_id: NotificationIdPath,
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
) -> NotificationRead:
    """이미 읽은 알림에 다시 호출해도 read_at 은 처음 읽은 시각을 유지"""
    try:
        return NotificationRead.model_validate(
            service.mark_read(current_user, notification_id)
        )
    except NotificationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "알림을 찾을 수 없습니다") from None
