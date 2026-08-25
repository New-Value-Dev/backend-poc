from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.deps import get_current_user, require_project_access, require_project_owner
from app.models.project import Project
from app.models.project_member import MEMBER_STATUS_ACTIVE
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectInvitationRead,
    ProjectMemberInvite,
    ProjectMemberRead,
    ProjectRead,
    ProjectUpdate,
    ProjectVisibilityUpdate,
)
from app.services.activity_service import (
    Action,
    ActivityService,
    get_activity_service,
)
from app.services.notification_service import (
    NotificationService,
    NotificationType,
    get_notification_service,
)
from app.services.project_service import (
    InviteeNotFoundError,
    ProjectForbiddenError,
    ProjectInvitationNotFoundError,
    ProjectMemberAlreadyExistsError,
    ProjectMemberInvitePendingError,
    ProjectMemberNotFoundError,
    ProjectService,
    get_project_service,
)

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectIdPath = Annotated[int, Path(description="프로젝트 id", examples=[1])]
UserIdPath = Annotated[int, Path(description="사용자 id", examples=[1])]

# 인증이 걸린 모든 엔드포인트가 공유하는 오류 응답 설명.
AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
NOT_FOUND_RESPONSE = {404: {"description": "해당 프로젝트가 없음"}}
FORBIDDEN_RESPONSE = {403: {"description": "이 프로젝트에 접근/조작할 권한이 없음"}}


def _display_name(user: User) -> str:
    """알림 문구에 쓸 표시 이름"""
    return user.name or user.email


@router.get(
    "",
    response_model=list[ProjectRead],
    summary="프로젝트 목록",
    response_description="접근 가능한(public 전체 + 내가 속한 invite + 내 private) 프로젝트를 id 오름차순으로",
    responses=AUTH_RESPONSES,
)
def list_projects(
    service: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> list[ProjectRead]:
    """public 전체 + 내가 멤버인 invite 프로젝트 + 내 소유 private 프로젝트만 보인다"""
    return service.list_projects(current_user)


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
    """새 프로젝트를 만든다. owner/created_by는 로그인 사용자로 서버가 채움"""
    project = service.create_project(payload, current_user)
    activity.record(
        Action.PROJECT_CREATE,
        project_id=project.id,
        target_type="project",
        target_id=project.id,
        target_label=project.name,
    )
    return project


# ── 내가 받은 초대 ──
# 경로 순서 주의: "/invitations" 는 반드시 "/{project_id}" 보다 먼저 선언해야 한다 —
# 아니면 FastAPI 가 "invitations" 를 project_id(int) 로 파싱하려다 422 를 낸다.


@router.get(
    "/invitations",
    response_model=list[ProjectInvitationRead],
    summary="내가 받은 수락 대기 초대 목록",
    response_description="아직 수락/거절하지 않은 초대를 최신순으로",
    responses=AUTH_RESPONSES,
)
def list_my_invitations(
    service: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> list[ProjectInvitationRead]:
    """초대받은 프로젝트는 이 엔드포인트로 확인한다."""
    return service.list_invitations(current_user)


@router.post(
    "/{project_id}/invitation/accept",
    response_model=ProjectRead,
    summary="초대 수락 (초대받은 본인)",
    response_description="이제 접근 가능해진 프로젝트",
    responses={
        **AUTH_RESPONSES,
        **NOT_FOUND_RESPONSE,
        400: {"description": "대기 중인 초대가 없음(이미 응답했거나 초대받지 않음)"},
    },
)
def accept_invitation(
    project_id: ProjectIdPath,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    notifications: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
) -> ProjectRead:
    """수락하면 멤버 상태가 active 가 되어 그때부터 프로젝트에 접근"""
    try:
        outcome = service.accept_invitation(project_id, current_user)
    except ProjectInvitationNotFoundError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "대기 중인 초대가 없습니다"
        ) from None
    activity.record(
        Action.PROJECT_MEMBER_ACCEPT,
        project_id=project_id,
        target_type="project",
        target_id=project_id,
        target_label=outcome.project.name,
    )
    if outcome.notify_user_id is not None:
        notifications.notify(
            outcome.notify_user_id,
            type=NotificationType.PROJECT_INVITE_ACCEPTED,
            title="초대 수락",
            body=f"{_display_name(current_user)}님이 '{outcome.project.name}' 초대를 수락했습니다.",
            url=f"/projects/{project_id}",
            meta={"project_id": project_id, "user_id": current_user.id},
        )
    return outcome.project


@router.post(
    "/{project_id}/invitation/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="초대 거절 (초대받은 본인)",
    response_description="본문 없음(204)",
    responses={
        **AUTH_RESPONSES,
        **NOT_FOUND_RESPONSE,
        400: {"description": "대기 중인 초대가 없음(이미 응답했거나 초대받지 않음)"},
    },
)
def decline_invitation(
    project_id: ProjectIdPath,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    notifications: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
) -> None:
    """거절해도 멤버 행은 status='rejected' 로 남아 owner 가 결과를 볼 수 있고,
    owner 가 다시 초대하면 pending 으로 되돌아간다."""
    try:
        outcome = service.decline_invitation(project_id, current_user)
    except ProjectInvitationNotFoundError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "대기 중인 초대가 없습니다"
        ) from None
    activity.record(
        Action.PROJECT_MEMBER_DECLINE,
        project_id=project_id,
        target_type="project",
        target_id=project_id,
        target_label=outcome.project.name,
    )
    if outcome.notify_user_id is not None:
        notifications.notify(
            outcome.notify_user_id,
            type=NotificationType.PROJECT_INVITE_DECLINED,
            title="초대 거절",
            body=f"{_display_name(current_user)}님이 '{outcome.project.name}' 초대를 거절했습니다.",
            url=f"/projects/{project_id}",
            meta={"project_id": project_id, "user_id": current_user.id},
        )


@router.get(
    "/{project_id}",
    response_model=ProjectRead,
    summary="프로젝트 상세",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE, **FORBIDDEN_RESPONSE},
)
def get_project(
    project: Project = Depends(require_project_access),
) -> ProjectRead:
    """프로젝트 하나를 조회한다."""
    return project


@router.patch(
    "/{project_id}",
    response_model=ProjectRead,
    summary="프로젝트 부분 수정 (이름/설명)",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE, **FORBIDDEN_RESPONSE},
)
def update_project(
    project_id: ProjectIdPath,
    payload: ProjectUpdate,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    _: Project = Depends(require_project_access),
) -> ProjectRead:
    """이름·설명을 부분 수정한다. 보낸 필드만 반영되고 생략한 필드는 기존 값을 유지한다.
    멤버라면 누구나 가능 — visibility 전환은 별도 엔드포인트(owner 전용)를 쓴다"""
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


@router.patch(
    "/{project_id}/visibility",
    response_model=ProjectRead,
    summary="프로젝트 가시성 전환 (owner 전용)",
    response_description="private/invite/public 중 하나로 전환된 프로젝트",
    responses={
        **AUTH_RESPONSES,
        **NOT_FOUND_RESPONSE,
        403: {"description": "owner(또는 admin)만 가능"},
    },
)
def update_project_visibility(
    project_id: ProjectIdPath,
    payload: ProjectVisibilityUpdate,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    _: Project = Depends(require_project_owner),
) -> ProjectRead:
    """개인 작업공간(private)을 완성 후 invite/public 으로 승격하거나, 반대로 잠글 때 사용한다"""
    project = service.update_visibility(project_id, payload.visibility)
    activity.record(
        Action.PROJECT_VISIBILITY_CHANGE,
        project_id=project.id,
        target_type="project",
        target_id=project.id,
        target_label=project.name,
        meta={"visibility": payload.visibility},
    )
    return project


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="프로젝트 삭제 (owner 전용)",
    response_description="본문 없음(204)",
    responses={
        **AUTH_RESPONSES,
        **NOT_FOUND_RESPONSE,
        403: {"description": "owner(또는 admin)만 가능"},
    },
)
def delete_project(
    project_id: ProjectIdPath,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    project: Project = Depends(require_project_owner),
) -> None:
    """프로젝트를 삭제한다. 소속 폴더·문서·버전·섹션·청크가 CASCADE로 함께 지워지며 되돌릴 수 없다"""
    name = project.name
    service.delete_project(project_id)
    activity.record(
        Action.PROJECT_DELETE,
        project_id=project_id,
        target_type="project",
        target_id=project_id,
        target_label=name,
    )


# ── 멤버 관리 (DESIGN.md §28) ──


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberRead],
    summary="프로젝트 멤버 목록",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE, **FORBIDDEN_RESPONSE},
)
def list_project_members(
    project_id: ProjectIdPath,
    service: ProjectService = Depends(get_project_service),
    _: Project = Depends(require_project_access),
) -> list[ProjectMemberRead]:
    """정식 멤버뿐 아니라 수락 대기(pending)/거절(rejected)도 함께 돌려줌"""
    return service.list_members(project_id)


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="멤버 초대 (owner 전용)",
    response_description="생성된 초대(201) — status='pending'",
    responses={
        **AUTH_RESPONSES,
        **NOT_FOUND_RESPONSE,
        403: {"description": "owner(또는 admin)만 가능"},
        400: {"description": "해당 사용자가 없거나, 이미 멤버이거나, 이미 초대 대기 중임"},
    },
)
def invite_project_member(
    project_id: ProjectIdPath,
    payload: ProjectMemberInvite,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    notifications: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
    project: Project = Depends(require_project_owner),
) -> ProjectMemberRead:
    """가입된 사용자를 user_id 또는 email 로 찾아 초대"""
    try:
        member = service.invite_member(
            project_id,
            email=payload.email,
            user_id=payload.user_id,
            invited_by=current_user,
        )
    except InviteeNotFoundError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"'{exc.identifier}' 로 가입된 사용자가 없습니다"
        ) from None
    except ProjectMemberAlreadyExistsError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "이미 멤버인 사용자입니다") from None
    except ProjectMemberInvitePendingError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "이미 초대해 수락을 기다리는 중입니다"
        ) from None
    activity.record(
        Action.PROJECT_MEMBER_INVITE,
        project_id=project_id,
        target_type="user",
        target_id=member.user_id,
        target_label=member.email,
    )
    notifications.notify(
        member.user_id,
        type=NotificationType.PROJECT_INVITE,
        title="프로젝트 초대",
        body=f"{_display_name(current_user)}님이 '{project.name}' 프로젝트에 초대했습니다.",
        url=f"/projects/{project_id}",
        meta={"project_id": project_id, "project_name": project.name},
    )
    return member


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="멤버 제거 / 초대 취소 (owner 전용)",
    response_description="본문 없음(204)",
    responses={
        **AUTH_RESPONSES,
        403: {"description": "owner(또는 admin)만 가능, 혹은 owner 본인은 제거 불가"},
        404: {"description": "프로젝트가 없거나 해당 사용자가 멤버/초대 대상이 아님"},
    },
)
def remove_project_member(
    project_id: ProjectIdPath,
    user_id: UserIdPath,
    service: ProjectService = Depends(get_project_service),
    activity: ActivityService = Depends(get_activity_service),
    notifications: NotificationService = Depends(get_notification_service),
    project: Project = Depends(require_project_owner),
) -> None:
    """정식 멤버 제거와 수락 전 초대 취소"""
    try:
        removed_status = service.remove_member(project_id, user_id)
    except ProjectMemberNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "멤버가 아닙니다") from None
    except ProjectForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "owner 본인은 제거할 수 없습니다"
        ) from None
    activity.record(
        Action.PROJECT_MEMBER_REMOVE,
        project_id=project_id,
        target_type="user",
        target_id=user_id,
        meta={"removed_status": removed_status},
    )
    if removed_status == MEMBER_STATUS_ACTIVE:
        notifications.notify(
            user_id,
            type=NotificationType.PROJECT_MEMBER_REMOVED,
            title="프로젝트 접근 종료",
            body=f"'{project.name}' 프로젝트 멤버에서 제외되었습니다.",
            meta={"project_id": project_id},
        )
