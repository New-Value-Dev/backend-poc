"""OAuth provider 추상화

- MockProvider: 크리덴셜 없이 로그인 플로우를 end-to-end 로 검증하기 위한 dev 전용
- GoogleProvider: 실제 Google OAuth

새 provider(사내 SSO 등)는 AuthProvider 프로토콜을 구현해 여기에 추가한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings

settings = get_settings()


@dataclass
class ExternalIdentity:
    provider: str
    sub: str
    email: str
    name: str | None


class ProviderError(Exception):
    """provider 설정 누락/토큰 교환 실패."""


class AuthProvider(Protocol):
    name: str

    def authorization_url(self, state: str, redirect_uri: str) -> str: ...

    def fetch_identity(self, code: str, redirect_uri: str) -> ExternalIdentity: ...


class MockProvider:
    """IdP 왕복 없이 곧바로 콜백으로 돌려보내는 dev provider."""

    name = "mock"

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        query = urlencode({"code": "mock-auth-code", "state": state})
        return f"{redirect_uri}?{query}"

    def fetch_identity(self, code: str, redirect_uri: str) -> ExternalIdentity:
        return ExternalIdentity(
            provider="mock",
            sub="dev-user-1",
            email="dev@local.test",
            name="Dev User",
        )


class GoogleProvider:
    name = "google"
    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105
    USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
    SCOPE = "openid email profile"

    def _require_credentials(self) -> tuple[str, str]:
        if not settings.google_client_id or not settings.google_client_secret:
            raise ProviderError(
                "Google OAuth 크리덴셜이 설정되지 않았습니다 "
                "(google_client_id / google_client_secret)."
            )
        return settings.google_client_id, settings.google_client_secret

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        client_id, _ = self._require_credentials()
        params = {
            "client_id": client_id,
            "redirect_uri": settings.google_redirect_uri or redirect_uri,
            "response_type": "code",
            "scope": self.SCOPE,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.AUTH_ENDPOINT}?{urlencode(params)}"

    def fetch_identity(self, code: str, redirect_uri: str) -> ExternalIdentity:
        client_id, client_secret = self._require_credentials()
        with httpx.Client(timeout=10.0) as client:
            token_res = client.post(
                self.TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": settings.google_redirect_uri or redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_res.status_code != 200:
                raise ProviderError(f"Google 토큰 교환 실패: {token_res.text}")
            access_token = token_res.json().get("access_token")

            info_res = client.get(
                self.USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if info_res.status_code != 200:
                raise ProviderError(f"Google userinfo 실패: {info_res.text}")
            info = info_res.json()

        return ExternalIdentity(
            provider="google",
            sub=info["sub"],
            email=info["email"],
            name=info.get("name"),
        )


_PROVIDERS: dict[str, AuthProvider] = {
    MockProvider.name: MockProvider(),
    GoogleProvider.name: GoogleProvider(),
}


def get_provider(name: str) -> AuthProvider:
    if name not in settings.auth_providers or name not in _PROVIDERS:
        raise ProviderError(f"지원하지 않거나 비활성 provider: {name}")
    return _PROVIDERS[name]
