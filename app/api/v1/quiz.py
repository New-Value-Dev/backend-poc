from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    status,
)

from app.api.deps import get_current_user, require_project_access
from app.core.timeutil import format_kst
from app.models.project import Project
from app.models.quiz_book import QuizBook
from app.models.quiz_generation_job import QuizGenerationJob
from app.models.quiz_question import QuizQuestion
from app.models.user import User
from app.schemas.quiz import (
    QuizAnswerGradeResult,
    QuizAnswerSubmit,
    QuizBookCreate,
    QuizBookQuestionsAdd,
    QuizBookRead,
    QuizBookUpdate,
    QuizDifficulty,
    QuizGenerateRequest,
    QuizGenerationJobRead,
    QuizQuestionCreate,
    QuizQuestionRead,
    QuizQuestionType,
    QuizQuestionUpdate,
    QuizReviewStatus,
    QuizSessionDraftRead,
    QuizSessionRead,
    QuizSessionResult,
    QuizSessionStart,
    QuizSessionStartResponse,
    QuizSessionStatus,
    QuizSessionSubmit,
)
from app.services.notification_service import (
    NotificationService,
    NotificationType,
    get_notification_service,
)
from app.services.project_service import (
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectService,
    get_project_service,
)
from app.services.quiz.planner import NoChunksError
from app.services.quiz_generation_service import (
    DocumentNotInProjectError,
    QuizGenerationJobNotFoundError,
    QuizGenerationService,
    get_quiz_generation_service,
    run_quiz_generation_task,
)
from app.services.quiz_service import (
    QuizAssigneeNotProjectMemberError,
    QuizBookForbiddenError,
    QuizBookLockedError,
    QuizBookNotFoundError,
    QuizQuestionNotFoundError,
    QuizService,
    QuizSessionAlreadySubmittedError,
    QuizSessionNotFoundError,
    can_manage_quiz_book,
    get_quiz_service,
)

router = APIRouter(tags=["quiz"])

ProjectIdPath = Annotated[int, Path(description="프로젝트 id", examples=[1])]
QuestionIdPath = Annotated[int, Path(description="문제은행 문제 id", examples=[1])]
QuizBookIdPath = Annotated[int, Path(description="문제집 id", examples=[1])]
SessionIdPath = Annotated[int, Path(description="응시 세션 id", examples=[1])]

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
FORBIDDEN_RESPONSE = {403: {"description": "이 리소스가 속한 프로젝트에 접근할 권한이 없음"}}


def _not_found(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, message)


def _check_project_access(
    project_id: int, projects: ProjectService, current_user: User, not_found_message: str
) -> None:
    try:
        projects.check_access(project_id, current_user)
    except ProjectForbiddenError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "이 프로젝트에 접근할 권한이 없습니다") from None
    except ProjectNotFoundError:
        raise _not_found(not_found_message) from None


def check_quiz_question_access(
    question_id: QuestionIdPath,
    service: QuizService = Depends(get_quiz_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> QuizQuestion:
    try:
        question = service.get_question(question_id)
    except QuizQuestionNotFoundError:
        raise _not_found(f"Quiz question {question_id} not found") from None
    _check_project_access(
        question.project_id, projects, current_user, f"Quiz question {question_id} not found"
    )
    return question


def check_quiz_book_access(
    quiz_book_id: QuizBookIdPath,
    service: QuizService = Depends(get_quiz_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> QuizBook:
    try:
        book = service.get_book(quiz_book_id)
    except QuizBookNotFoundError:
        raise _not_found(f"Quiz book {quiz_book_id} not found") from None
    _check_project_access(
        book.project_id, projects, current_user, f"Quiz book {quiz_book_id} not found"
    )
    return book


def require_quiz_book_manager(
    book: QuizBook = Depends(check_quiz_book_access),
    current_user: User = Depends(get_current_user),
) -> QuizBook:
    """설정/문제 구성을 바꾸는 라우트 전용"""
    if not can_manage_quiz_book(book, current_user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "이 문제집을 만든 사람 또는 프로젝트 소유자만 관리할 수 있습니다"
        )
    return book


# ── 문제은행 ──


@router.get(
    "/projects/{project_id}/quiz-questions",
    response_model=list[QuizQuestionRead],
    summary="문제은행 목록",
    responses={**AUTH_RESPONSES, 404: {"description": "프로젝트 없음"}, **FORBIDDEN_RESPONSE},
)
def list_quiz_questions(
    project_id: ProjectIdPath,
    document_id: Annotated[int | None, Query(description="출처 문서로 필터")] = None,
    difficulty: Annotated[QuizDifficulty | None, Query()] = None,
    type: Annotated[QuizQuestionType | None, Query()] = None,
    review_status: Annotated[QuizReviewStatus | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, description="문제 본문 검색어")] = None,
    service: QuizService = Depends(get_quiz_service),
    _: Project = Depends(require_project_access),
) -> list[QuizQuestion]:
    return service.list_questions(
        project_id,
        document_id=document_id,
        difficulty=difficulty.value if difficulty else None,
        type=type.value if type else None,
        review_status=review_status.value if review_status else None,
        q=q,
    )


@router.post(
    "/projects/{project_id}/quiz-questions",
    response_model=QuizQuestionRead,
    status_code=status.HTTP_201_CREATED,
    summary="문제 직접 작성",
    responses={**AUTH_RESPONSES, 404: {"description": "프로젝트 없음"}, **FORBIDDEN_RESPONSE},
)
def create_quiz_question(
    project_id: ProjectIdPath,
    payload: QuizQuestionCreate,
    service: QuizService = Depends(get_quiz_service),
    _: Project = Depends(require_project_access),
) -> QuizQuestion:
    return service.create_question(project_id, payload)


@router.patch(
    "/quiz-questions/{question_id}",
    response_model=QuizQuestionRead,
    summary="문제 수정",
    responses={**AUTH_RESPONSES, 404: {"description": "문제 없음"}, **FORBIDDEN_RESPONSE},
)
def update_quiz_question(
    payload: QuizQuestionUpdate,
    service: QuizService = Depends(get_quiz_service),
    question: QuizQuestion = Depends(check_quiz_question_access),
) -> QuizQuestion:
    return service.update_question(question.id, payload)


@router.delete(
    "/quiz-questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="문제은행에서 완전 삭제",
    response_description="본문 없음(204). 이 문제를 담고 있던 모든 문제집에서도 연결이 함께 해제된다",
    responses={**AUTH_RESPONSES, 404: {"description": "문제 없음"}, **FORBIDDEN_RESPONSE},
)
def delete_quiz_question(
    service: QuizService = Depends(get_quiz_service),
    question: QuizQuestion = Depends(check_quiz_question_access),
) -> None:
    service.delete_question(question.id)


# ── AI 문제 생성 ──


LOCKED_RESPONSE = "응시 이력이 있는 문제집은 수정할 수 없습니다. 먼저 복제하세요"


def check_quiz_generation_job_access(
    job_id: Annotated[int, Path(description="생성 작업 id", examples=[1])],
    service: QuizGenerationService = Depends(get_quiz_generation_service),
    current_user: User = Depends(get_current_user),
) -> QuizGenerationJob:
    """본인 잡만 조회 — 남의 잡은 존재를 숨기고 404."""
    try:
        return service.get_job(job_id, current_user.id)
    except QuizGenerationJobNotFoundError:
        raise _not_found(f"Quiz generation job {job_id} not found") from None


@router.post(
    "/projects/{project_id}/quiz-questions/generate",
    response_model=QuizGenerationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="AI 문제 생성 시작 (비동기)",
    response_description="`status=\"RUNNING\"` 인 생성 작업(202). 폴링으로 결과를 확인한다",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "프로젝트/문제집 없음, 또는 문서가 이 프로젝트 소속이 아님"},
        403: {"description": "이 문제집을 만든 사람 또는 프로젝트 소유자가 아님(quiz_book_id 지정 시)"},
        409: {"description": "대상 문서에 청크가 없음(파싱/청킹 전), 또는 문제집에 응시 이력이 있음"},
        **FORBIDDEN_RESPONSE,
    },
)
def generate_quiz_questions(
    project_id: ProjectIdPath,
    payload: QuizGenerateRequest,
    background_tasks: BackgroundTasks,
    service: QuizGenerationService = Depends(get_quiz_generation_service),
    current_user: User = Depends(get_current_user),
    _: Project = Depends(require_project_access),
) -> QuizGenerationJob:
    """지정한 문서들로 문제를 생성"""
    try:
        job = service.start(project_id, current_user, payload)
    except NoChunksError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except QuizBookLockedError:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCKED_RESPONSE) from None
    except QuizBookNotFoundError:
        raise _not_found(f"Quiz book {payload.quiz_book_id} not found") from None
    except QuizBookForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "이 문제집을 만든 사람 또는 프로젝트 소유자만 관리할 수 있습니다"
        ) from None
    except DocumentNotInProjectError as exc:
        raise _not_found(f"Document {exc.document_id} not found in this project") from None

    background_tasks.add_task(run_quiz_generation_task, job.id)
    return job


@router.get(
    "/quiz-generation-jobs/{job_id}",
    response_model=QuizGenerationJobRead,
    summary="AI 문제 생성 상태 폴링",
    response_description="`status` 가 RUNNING 이면 계속 폴링. `created_count` 는 진행 중에도 올라간다",
    responses={**AUTH_RESPONSES, 404: {"description": "생성 작업 없음"}},
)
def get_quiz_generation_job(
    job: QuizGenerationJob = Depends(check_quiz_generation_job_access),
) -> QuizGenerationJob:
    """생성 진행 상황 확인"""
    return job


# ── 문제집 ──


@router.get(
    "/projects/{project_id}/quizzes",
    response_model=list[QuizBookRead],
    summary="문제집 목록",
    responses={**AUTH_RESPONSES, 404: {"description": "프로젝트 없음"}, **FORBIDDEN_RESPONSE},
)
def list_quiz_books(
    project_id: ProjectIdPath,
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    _: Project = Depends(require_project_access),
) -> list[QuizBookRead]:
    return service.list_books(project_id, current_user)


def _notify_quiz_assigned(
    notifications: NotificationService, book: QuizBookRead, user_ids: list[int]
) -> None:
    body = f"마감: {format_kst(book.due_at)}" if book.due_at else None
    for user_id in user_ids:
        notifications.notify(
            user_id,
            type=NotificationType.QUIZ_ASSIGNED,
            title=f"'{book.title}' 퀴즈가 배정되었습니다",
            body=body,
            url=f"/quiz/{book.id}/take",
            meta={"quiz_book_id": book.id, "project_id": book.project_id},
        )


@router.post(
    "/projects/{project_id}/quizzes",
    response_model=QuizBookRead,
    status_code=status.HTTP_201_CREATED,
    summary="문제집 생성",
    response_description="`assignee_user_ids`를 지정하면 생성 즉시 해당 사용자에게 알림이 발송된다",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "프로젝트 없음"},
        400: {
            "description": "assignee_user_ids 중 지정할 수 없는 사용자가 있음"
            "(비공개/초대 프로젝트: 활성 멤버가 아님, 공개 프로젝트: 존재하는 활성 사용자가 아님)"
        },
        **FORBIDDEN_RESPONSE,
    },
)
def create_quiz_book(
    project_id: ProjectIdPath,
    payload: QuizBookCreate,
    service: QuizService = Depends(get_quiz_service),
    notifications: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
    _: Project = Depends(require_project_access),
) -> QuizBookRead:
    try:
        outcome = service.create_book(project_id, payload, current_user)
    except QuizAssigneeNotProjectMemberError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"지정한 사용자 중 응시자로 지정할 수 없는 사용자가 있습니다: {exc.user_ids}",
        ) from None
    _notify_quiz_assigned(notifications, outcome.book, outcome.notify_user_ids)
    return outcome.book


@router.get(
    "/quizzes/{quiz_book_id}",
    response_model=QuizBookRead,
    summary="문제집 상세",
    responses={**AUTH_RESPONSES, 404: {"description": "문제집 없음"}, **FORBIDDEN_RESPONSE},
)
def get_quiz_book(
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(check_quiz_book_access),
) -> QuizBookRead:
    return service.get_book_read(book.id, current_user)


@router.patch(
    "/quizzes/{quiz_book_id}",
    response_model=QuizBookRead,
    summary="문제집 설정 수정",
    response_description="assignee_user_ids를 보내면 전체 지정자 목록이 그걸로 교체되고,"
    " 새로 추가된 사용자에게만 알림이 발송된다(기존 지정자는 재발송 안 함)",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "문제집 없음"},
        403: {"description": "이 문제집을 만든 사람 또는 프로젝트 소유자가 아님"},
        409: {"description": "응시 이력이 있어 수정할 수 없음 — /duplicate 로 복제할 것"},
        400: {
            "description": "assignee_user_ids 중 지정할 수 없는 사용자가 있음"
            "(비공개/초대 프로젝트: 활성 멤버가 아님, 공개 프로젝트: 존재하는 활성 사용자가 아님)"
        },
    },
)
def update_quiz_book(
    payload: QuizBookUpdate,
    service: QuizService = Depends(get_quiz_service),
    notifications: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(require_quiz_book_manager),
) -> QuizBookRead:
    try:
        outcome = service.update_book(book.id, payload, current_user)
    except QuizBookLockedError:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCKED_RESPONSE) from None
    except QuizAssigneeNotProjectMemberError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"지정한 사용자 중 응시자로 지정할 수 없는 사용자가 있습니다: {exc.user_ids}",
        ) from None
    _notify_quiz_assigned(notifications, outcome.book, outcome.notify_user_ids)
    return outcome.book


@router.delete(
    "/quizzes/{quiz_book_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="문제집 삭제",
    response_description="본문 없음(204). 응시 이력이 있어도 삭제는 허용되며, 세션/답변도 함께 삭제된다",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "문제집 없음"},
        403: {"description": "이 문제집을 만든 사람 또는 프로젝트 소유자가 아님"},
    },
)
def delete_quiz_book(
    service: QuizService = Depends(get_quiz_service),
    book: QuizBook = Depends(require_quiz_book_manager),
) -> None:
    service.delete_book(book.id)


@router.post(
    "/quizzes/{quiz_book_id}/duplicate",
    response_model=QuizBookRead,
    status_code=status.HTTP_201_CREATED,
    summary="문제집 복제",
    response_description="설정 + 문제 구성을 그대로 복사한 새 문제집(세션 없음)",
    responses={**AUTH_RESPONSES, 404: {"description": "문제집 없음"}, **FORBIDDEN_RESPONSE},
)
def duplicate_quiz_book(
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(check_quiz_book_access),
) -> QuizBookRead:
    return service.duplicate_book(book.id, current_user)


@router.get(
    "/quizzes/{quiz_book_id}/questions",
    response_model=list[QuizQuestionRead],
    summary="문제집 소속 문제 목록",
    response_description="문제집 내 순서대로",
    responses={**AUTH_RESPONSES, 404: {"description": "문제집 없음"}, **FORBIDDEN_RESPONSE},
)
def list_quiz_book_questions(
    service: QuizService = Depends(get_quiz_service),
    book: QuizBook = Depends(check_quiz_book_access),
) -> list[QuizQuestion]:
    return service.list_book_questions(book.id)


@router.post(
    "/quizzes/{quiz_book_id}/questions",
    response_model=list[QuizQuestionRead],
    summary="문제은행에서 문제 편입",
    response_description="편입 후 문제집 소속 문제 전체 목록(순서대로)",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "문제집 없음"},
        403: {"description": "이 문제집을 만든 사람 또는 프로젝트 소유자가 아님"},
        409: {"description": "응시 이력이 있어 수정할 수 없음 — /duplicate 로 복제할 것"},
    },
)
def add_quiz_book_questions(
    payload: QuizBookQuestionsAdd,
    service: QuizService = Depends(get_quiz_service),
    book: QuizBook = Depends(require_quiz_book_manager),
) -> list[QuizQuestion]:
    try:
        return service.add_questions_to_book(book.id, payload.question_ids)
    except QuizBookLockedError:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCKED_RESPONSE) from None


@router.delete(
    "/quizzes/{quiz_book_id}/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="문제집에서 연결 해제",
    response_description="본문 없음(204). 문제은행에서는 삭제되지 않는다",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "문제집 없음"},
        403: {"description": "이 문제집을 만든 사람 또는 프로젝트 소유자가 아님"},
        409: {"description": "응시 이력이 있어 수정할 수 없음 — /duplicate 로 복제할 것"},
    },
)
def remove_quiz_book_question(
    question_id: QuestionIdPath,
    service: QuizService = Depends(get_quiz_service),
    book: QuizBook = Depends(require_quiz_book_manager),
) -> None:
    try:
        service.remove_question_from_book(book.id, question_id)
    except QuizBookLockedError:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCKED_RESPONSE) from None


# ── 응시 ──


@router.post(
    "/quizzes/{quiz_book_id}/sessions",
    response_model=QuizSessionStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="응시 시작 (진행중 세션이 있으면 재개)",
    response_description="정답이 빠진 문제 목록 + session_id. 이미 진행중인 세션이 있으면"
    " 새로 만들지 않고 그 세션을 그대로 돌려준다(resumed=true, 문항 순서 동일)",
    responses={**AUTH_RESPONSES, 404: {"description": "문제집 없음"}, **FORBIDDEN_RESPONSE},
)
def start_quiz_session(
    payload: QuizSessionStart,
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(check_quiz_book_access),
) -> QuizSessionStartResponse:
    session, questions, answers, resumed, draft_answers = service.start_session(
        book.id, current_user.id, payload.mode.value
    )
    return QuizSessionStartResponse(
        session_id=session.id,
        mode=session.mode,
        questions=questions,
        resumed=resumed,
        answers=answers,
        draft_answers=draft_answers,
    )


@router.patch(
    "/quizzes/{quiz_book_id}/sessions/{session_id}/draft",
    response_model=QuizSessionDraftRead,
    summary="exam 모드 자동저장 (채점 없이 답만 저장)",
    response_description="저장 후 이 세션의 전체 임시 답안 맵",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "세션 또는 문제 없음"},
        409: {"description": "이미 제출된 세션"},
        **FORBIDDEN_RESPONSE,
    },
)
def save_quiz_draft_answer(
    session_id: SessionIdPath,
    payload: QuizAnswerSubmit,
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(check_quiz_book_access),
) -> QuizSessionDraftRead:
    """exam 모드에서 답을 고를 때마다 호출"""
    try:
        draft = service.save_draft_answer(
            book.id, session_id, current_user.id, payload.question_id, payload.user_answer
        )
    except QuizSessionNotFoundError:
        raise _not_found(f"Quiz session {session_id} not found") from None
    except QuizQuestionNotFoundError:
        raise _not_found(f"Quiz question {payload.question_id} not found in this quiz book") from None
    except QuizSessionAlreadySubmittedError:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 제출된 세션입니다") from None
    return QuizSessionDraftRead(draft_answers=draft)


@router.post(
    "/quizzes/{quiz_book_id}/sessions/{session_id}/answers",
    response_model=QuizAnswerGradeResult,
    summary="학습 모드 즉시 채점",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "세션 또는 문제 없음"},
        409: {"description": "이미 제출된 세션"},
        **FORBIDDEN_RESPONSE,
    },
)
def grade_quiz_answer(
    session_id: SessionIdPath,
    payload: QuizAnswerSubmit,
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(check_quiz_book_access),
) -> QuizAnswerGradeResult:
    try:
        return service.grade_answer(
            book.id, session_id, current_user.id, payload.question_id, payload.user_answer
        )
    except QuizSessionNotFoundError:
        raise _not_found(f"Quiz session {session_id} not found") from None
    except QuizQuestionNotFoundError:
        raise _not_found(f"Quiz question {payload.question_id} not found in this quiz book") from None
    except QuizSessionAlreadySubmittedError:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 제출된 세션입니다") from None


@router.post(
    "/quizzes/{quiz_book_id}/sessions/{session_id}/submit",
    response_model=QuizSessionResult,
    summary="최종 제출",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "세션 없음"},
        409: {"description": "이미 제출된 세션"},
        **FORBIDDEN_RESPONSE,
    },
)
def submit_quiz_session(
    session_id: SessionIdPath,
    payload: QuizSessionSubmit,
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(check_quiz_book_access),
) -> QuizSessionResult:
    try:
        return service.submit_session(book.id, session_id, current_user.id, payload.answers)
    except QuizSessionNotFoundError:
        raise _not_found(f"Quiz session {session_id} not found") from None
    except QuizSessionAlreadySubmittedError:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 제출된 세션입니다") from None


@router.get(
    "/quizzes/{quiz_book_id}/sessions",
    response_model=list[QuizSessionRead],
    summary="문제집별 응시 이력",
    response_description="문제집 관리자면 이 문제집을 응시한 모든 사용자의 세션 요약(이름 포함)."
    " 관리자가 아니면 본인 세션만 — 문항별 답변은 상세 조회로",
    responses={**AUTH_RESPONSES, 404: {"description": "문제집 없음"}, **FORBIDDEN_RESPONSE},
)
def list_quiz_book_sessions(
    status_filter: Annotated[
        QuizSessionStatus | None, Query(alias="status", description="지정하면 그 상태만")
    ] = None,
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(check_quiz_book_access),
) -> list:
    return service.get_book_sessions(
        book.id, current_user, status=status_filter.value if status_filter else None
    )


@router.get(
    "/quizzes/{quiz_book_id}/sessions/{session_id}",
    response_model=QuizSessionResult,
    summary="세션 상세 (오답노트)",
    response_description="본인 세션이거나 문제집 관리자면 조회 가능. 관리자가 남의 세션을 볼 때는"
    " reveal_answers 설정과 무관하게 정답/해설이 항상 보인다",
    responses={**AUTH_RESPONSES, 404: {"description": "세션 없음(남의 세션이고 관리자도 아니면 404)"}, **FORBIDDEN_RESPONSE},
)
def get_quiz_session(
    session_id: SessionIdPath,
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    book: QuizBook = Depends(check_quiz_book_access),
) -> QuizSessionResult:
    try:
        return service.get_session_detail(book.id, session_id, current_user)
    except QuizSessionNotFoundError:
        raise _not_found(f"Quiz session {session_id} not found") from None


@router.get(
    "/projects/{project_id}/quiz-sessions",
    response_model=list[QuizSessionRead],
    summary="내 응시 이력 (문제집 전체)",
    response_description="이 프로젝트 안에서 내가 응시한 모든 세션 요약"
    " — status=IN_PROGRESS 로 필터하면 '이어서 풀기' 목록으로 쓸 수 있다",
    responses={**AUTH_RESPONSES, 404: {"description": "프로젝트 없음"}, **FORBIDDEN_RESPONSE},
)
def list_my_quiz_sessions(
    project_id: ProjectIdPath,
    status_filter: Annotated[
        QuizSessionStatus | None, Query(alias="status", description="지정하면 그 상태만")
    ] = None,
    service: QuizService = Depends(get_quiz_service),
    current_user: User = Depends(get_current_user),
    _: Project = Depends(require_project_access),
) -> list:
    return service.get_project_sessions(
        project_id, current_user.id, status=status_filter.value if status_filter else None
    )
