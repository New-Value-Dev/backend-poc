from fastapi import APIRouter, Depends, Request, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.push import (
    PublicKeyResponse,
    PushSubscribeRequest,
    PushUnsubscribeRequest,
)
from app.services.push_service import PushService, get_push_service

router = APIRouter(prefix="/push", tags=["push"])

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}


@router.get(
    "/public-key",
    response_model=PublicKeyResponse,
    summary="VAPID 공개키 조회",
    response_description="브라우저 PushManager.subscribe()의 applicationServerKey에 쓸 공개키",
)
def get_public_key(
    service: PushService = Depends(get_push_service),
) -> PublicKeyResponse:
    return PublicKeyResponse(public_key=service.public_key() or "")


@router.post(
    "/subscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="브라우저 push 구독 등록",
    responses=AUTH_RESPONSES,
)
def subscribe(
    body: PushSubscribeRequest,
    request: Request,
    service: PushService = Depends(get_push_service),
    user: User = Depends(get_current_user),
) -> None:
    """같은 endpoint로 재구독하면 키를 갱신"""
    service.subscribe(user, body, user_agent=request.headers.get("user-agent"))


@router.delete(
    "/subscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="브라우저 push 구독 해제",
    responses=AUTH_RESPONSES,
)
def unsubscribe(
    body: PushUnsubscribeRequest,
    service: PushService = Depends(get_push_service),
    user: User = Depends(get_current_user),
) -> None:
    service.unsubscribe(body)
