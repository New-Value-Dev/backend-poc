from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import ACCESS_TOKEN_TYPE, TokenError, decode_token
from app.models.project import Project
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.project_service import (
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectService,
    get_project_service,
)

_bearer = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(credentials.credentials, ACCESS_TOKEN_TYPE)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 토큰",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    user = UserRepository(db).get(int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없거나 비활성 상태",
        )
    return user


def require_project_access(
    project_id: int,
    service: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> Project:
    """`{project_id}` 를 경로에 갖는 라우트에서 `Depends(require_project_access)` 로 쓴다."""
    try:
        return service.check_access(project_id, current_user)
    except ProjectNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Project {project_id} not found"
        ) from None
    except ProjectForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "이 프로젝트에 접근할 권한이 없습니다"
        ) from None


def require_project_owner(
    project_id: int,
    service: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> Project:
    """삭제/visibility 전환/멤버 관리처럼 owner(또는 admin) 전용 작업에 쓴다."""
    try:
        return service.check_owner(project_id, current_user)
    except ProjectNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Project {project_id} not found"
        ) from None
    except ProjectForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "이 작업은 프로젝트 소유자만 할 수 있습니다"
        ) from None
