import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import ProvidersResponse, TokenResponse, UserRead
from app.services.activity_service import Action, activity_service_for
from app.services.auth_providers import ProviderError, get_provider
from app.services.auth_service import AuthService, get_auth_service

settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
STATE_COOKIE = "oauth_state"
FRONTEND_COOKIE = "oauth_frontend"
COOKIE_PATH = "/api/v1/auth"

ProviderPath = Annotated[
    str,
    Path(
        description="`GET /auth/providers` 가 돌려준 provider 키. 예: `google`, `mock`",
        examples=["mock"],
    ),
]


def _callback_url(request: Request, provider: str) -> str:
    return str(request.url_for("auth_callback", provider=provider))


def _frontend_origin(request: Request, requested_origin: str | None = None) -> str:
    """로그인을 시작한 프론트 origin을 결정"""
    if requested_origin and requested_origin in settings.cors_allow_origins:
        return requested_origin

    referer = request.headers.get("referer")
    if referer:
        parsed = urlsplit(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in settings.cors_allow_origins:
            return origin
    return settings.frontend_url


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=COOKIE_PATH,
        max_age=settings.refresh_token_expire_days * 86400,
    )


@router.get(
    "/providers",
    response_model=ProvidersResponse,
    summary="활성 로그인 수단 목록",
    response_description='예: `{"providers": ["mock", "google"]}`',
)
def list_providers() -> ProvidersResponse:
    """이 서버에서 쓸 수 있는 OAuth provider 키를 돌려줌"""
    return ProvidersResponse(providers=settings.auth_providers)


@router.get(
    "/login/{provider}",
    summary="OAuth 로그인 시작 (브라우저 전용)",
    response_description="IdP 인증 페이지로 307 리다이렉트 + state 쿠키",
    responses={400: {"description": "지원하지 않는 provider"}},
)
def login(
    provider: ProviderPath,
    request: Request,
    origin: Annotated[
        str | None,
        Query(
            description=(
                "로그인을 시작한 프론트 origin (`window.location.origin`). "
                "PC(localhost)와 휴대폰(LAN IP/도메인)을 구분해 콜백을 돌려보내는 데 쓰인다. "
                "`CORS_ALLOW_ORIGINS` 화이트리스트에 없는 값은 무시된다."
            ),
            examples=["http://192.168.0.32:3000"],
        ),
    ] = None,
) -> RedirectResponse:
    """IdP 인증 페이지로 리다이렉트하고, CSRF 방지용 state를 쿠키에 심는다"""
    try:
        prov = get_provider(provider)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    state = secrets.token_urlsafe(24)
    redirect_uri = _callback_url(request, provider)
    response = RedirectResponse(prov.authorization_url(state, redirect_uri))
    response.set_cookie(
        STATE_COOKIE,
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=COOKIE_PATH,
        max_age=600,
    )
    response.set_cookie(
        FRONTEND_COOKIE,
        _frontend_origin(request, origin),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=COOKIE_PATH,
        max_age=600,
    )
    return response


@router.get(
    "/callback/{provider}",
    name="auth_callback",
    summary="OAuth 콜백 (IdP 가 호출)",
    response_description="프론트 `/auth/callback` 으로 307 리다이렉트 + refresh 쿠키",
    responses={400: {"description": "state 불일치 또는 code 교환 실패"}},
)
def callback(
    provider: ProviderPath,
    request: Request,
    code: Annotated[
        str, Query(description="IdP 가 붙여 주는 authorization code")
    ] = "",
    state: Annotated[
        str, Query(description="로그인 시작 때 심은 state. 쿠키 값과 일치해야 한다(CSRF 방지)")
    ] = "",
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """IdP 가 리다이렉트로 호출하는 엔드포인트"""
    expected_state = request.cookies.get(STATE_COOKIE)
    if not expected_state or expected_state != state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid oauth state")

    try:
        prov = get_provider(provider)
        identity = prov.fetch_identity(code, _callback_url(request, provider))
    except ProviderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    user = auth_service.get_or_create_user(identity)
    # 인증이 막 끝난 시점이라 get_current_user DI 를 쓸 수 없어 직접 만든다.
    activity_service_for(db, actor=user).record(
        Action.LOGIN, meta={"provider": provider}
    )
    refresh = create_refresh_token(user.id)

    frontend_origin = request.cookies.get(FRONTEND_COOKIE) or settings.frontend_url
    response = RedirectResponse(f"{frontend_origin}/auth/callback")
    _set_refresh_cookie(response, refresh)
    response.delete_cookie(STATE_COOKIE, path=COOKIE_PATH)
    response.delete_cookie(FRONTEND_COOKIE, path=COOKIE_PATH)
    return response


@router.post(
    "/token/refresh",
    response_model=TokenResponse,
    summary="access 토큰 재발급",
    response_description="`access_token` + 만료까지 남은 초(`expires_in`)",
    responses={401: {"description": "refresh 쿠키 없음/만료/무효, 또는 비활성 사용자"}},
)
def refresh_access_token(
    request: Request, db: Session = Depends(get_db)
) -> TokenResponse:
    """httpOnly refresh 쿠키를 검증하고 새 access 토큰 발급"""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no refresh token")
    try:
        payload = decode_token(token, REFRESH_TOKEN_TYPE)
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from None

    user = UserRepository(db).get(int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or inactive")

    access = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=access,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="로그아웃",
    response_description="본문 없음(204)",
)
def logout(response: Response) -> None:
    """refresh 쿠키 삭제"""
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


@router.get(
    "/me",
    response_model=UserRead,
    summary="현재 로그인 사용자",
    response_description="`id`, `email`, `name`, `role`",
    responses={401: {"description": "토큰 없음/만료/무효"}},
)
def me(current_user: User = Depends(get_current_user)) -> User:
    """Bearer 토큰이 가리키는 사용자 정보를 돌려줌"""
    return current_user
