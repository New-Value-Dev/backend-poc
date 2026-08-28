from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class QuizQuestionType(str, Enum):
    SINGLE_CHOICE = "SINGLE_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"
    SHORT_ANSWER = "SHORT_ANSWER"
    ESSAY = "ESSAY"


class QuizDifficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class QuizReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"


class QuizSessionMode(str, Enum):
    STUDY = "study"
    EXAM = "exam"


class QuizSessionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"


# ── 문제은행 ──


class QuizQuestionCreate(BaseModel):
    """문제 직접 작성(수동) : generation_type=MANUAL, review_status=DRAFT 로 생성"""

    type: QuizQuestionType
    text: str
    options: list[str] | None = Field(default=None, description="SINGLE_CHOICE에서만 사용")
    correct_answer: str
    explanation: str
    difficulty: QuizDifficulty
    tags: list[str] = Field(default_factory=list)
    source_document_id: int | None = None
    source_location: str | None = None


class QuizQuestionUpdate(BaseModel):
    """부분 수정 — 지정한 필드만 반영"""

    type: QuizQuestionType | None = None
    text: str | None = None
    options: list[str] | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    difficulty: QuizDifficulty | None = None
    tags: list[str] | None = None
    source_document_id: int | None = None
    source_location: str | None = None
    review_status: QuizReviewStatus | None = None


class QuizQuestionRead(BaseModel):
    """문제은행/편집용 — 정답/해설 포함"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    source_document_id: int | None
    source_document_title: str | None = Field(
        description="출처 문서명 — '분야별 정답률'을 태그 대신 이 값으로 그룹핑할 것"
    )
    type: str
    text: str
    options: list[str] | None
    correct_answer: str
    explanation: str
    difficulty: str
    tags: list[str] | None
    source_location: str | None
    generation_type: str
    review_status: str
    created_at: datetime
    updated_at: datetime


class QuizQuestionPlay(BaseModel):
    """응시 중 클라이언트에 내려주는 문항 — 정답/해설 제외"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    text: str
    options: list[str] | None
    difficulty: str


# ── 문제집 ──


class QuizBookCreate(BaseModel):
    title: str
    description: str | None = None
    source_document_ids: list[int] = Field(default_factory=list)
    passing_score: int = 60
    time_limit_minutes: int | None = None
    shuffle_questions: bool = False
    shuffle_options: bool = False
    allow_retake: bool = True
    reveal_answers: bool = True
    due_at: datetime | None = Field(default=None, description="응시 마감기한 — 지정하면 마감 임박 시 지정자에게 리마인더 발송")
    assignee_user_ids: list[int] = Field(
        default_factory=list, description="이 문제집을 풀어야 할 사람(프로젝트 활성 멤버만) — 지정하면 알림 발송"
    )


class QuizBookUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    source_document_ids: list[int] | None = None
    passing_score: int | None = None
    time_limit_minutes: int | None = None
    shuffle_questions: bool | None = None
    shuffle_options: bool | None = None
    allow_retake: bool | None = None
    reveal_answers: bool | None = None
    due_at: datetime | None = None
    assignee_user_ids: list[int] | None = Field(
        default=None, description="지정하면 전체 지정자 목록을 이걸로 교체한다. 새로 추가된 사람에게만 알림 발송"
    )


class QuizBookAssigneeRead(BaseModel):
    """이 문제집을 풀어야 할 사람으로 지정된 사용자"""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str | None = None
    user_email: str | None = None
    assigned_at: datetime


class QuizBookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: str | None
    source_document_ids: list[int] | None
    passing_score: int
    time_limit_minutes: int | None
    shuffle_questions: bool
    shuffle_options: bool
    allow_retake: bool
    reveal_answers: bool
    due_at: datetime | None = Field(description="응시 마감기한 — 없으면 마감 없음")
    assignees: list[QuizBookAssigneeRead] = Field(
        default_factory=list, description="이 문제집을 풀어야 할 사람으로 지정된 사용자 목록"
    )
    has_sessions: bool = Field(
        description="true면 응시 이력이 있어 설정/문제 구성 수정이 409로 막힌다 — /duplicate로 복제할 것"
    )
    created_by_user_id: int | None = Field(
        description="문제집을 만든 사용자. null이면 생성자 미상(과거 데이터) — 이 경우 프로젝트 소유자만 관리 가능"
    )
    can_manage: bool = Field(
        description="현재 로그인한 사용자가 이 문제집을 수정/삭제/문항 편입할 수 있는지"
    )
    created_at: datetime
    updated_at: datetime


class QuizBookQuestionsAdd(BaseModel):
    question_ids: list[int]


# ── AI 문제 생성 ──


class QuizGenerateRequest(BaseModel):
    """AI 문제 생성 요청 — 문서/질문 수, 난이도, 유형 등을 지정하면 서버가 배치로 생성"""

    document_ids: list[int] = Field(min_length=1, description="출제 대상 문서")
    count: int = Field(default=10, ge=1, description="생성할 문항 수 (상한은 서버 설정)")
    types: list[QuizQuestionType] = Field(
        default_factory=lambda: list(QuizQuestionType), description="허용 문항 유형"
    )
    difficulty: QuizDifficulty | None = Field(
        default=None, description="생략하면 난이도를 섞어서 출제"
    )
    exclude_duplicates: bool = Field(
        default=True, description="기존 문제은행 문항과 중복되는 문제를 피한다"
    )
    quiz_book_id: int | None = Field(
        default=None,
        description="지정하면 생성된 문항을 이 문제집에 자동 편입 (응시 이력이 있으면 409)",
    )


class QuizGenerationJobRead(BaseModel):
    """생성 작업 상태 -> `status`가 RUNNING이면 폴링"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: int
    quiz_book_id: int | None
    status: str
    requested_count: int
    # 배치마다 커밋되므로 RUNNING 중에도 올라간다 → 진행률로 쓸 수 있다
    created_count: int
    question_ids: list[int] | None
    provider: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


# ── 응시 ──


class QuizSessionStart(BaseModel):
    mode: QuizSessionMode = QuizSessionMode.EXAM


class QuizAnswerRecord(BaseModel):
    """제출 결과 / 재개 시의 문항별 답변 1건"""

    question_id: int | None
    question_text: str
    options: list[str] | None
    user_answer: str
    is_correct: bool
    correct_answer: str | None
    explanation: str | None
    score: float | None = Field(
        default=None, description="ESSAY 문항만 해당(0~100) — GPT 채점 점수"
    )
    feedback: str | None = Field(default=None, description="ESSAY 문항만 해당 — GPT 채점 코멘트")


class QuizSessionStartResponse(BaseModel):
    """세션 시작 응답 — 정답이 빠진 문항 목록 + session_id"""

    session_id: int
    mode: str
    questions: list[QuizQuestionPlay]
    resumed: bool = Field(default=False, description="true면 기존 진행중 세션을 재개한 것")
    answers: list[QuizAnswerRecord] = Field(
        default_factory=list, description="재개 시 이미 채점된 답변(study 모드만 해당)"
    )
    draft_answers: dict[str, str] = Field(
        default_factory=dict,
        description="재개 시 자동저장된 미채점 답안(question_id(문자열) -> 답, exam 모드용)",
    )


class QuizAnswerSubmit(BaseModel):
    question_id: int
    user_answer: str


class QuizSessionDraftRead(BaseModel):
    """자동저장 응답"""

    draft_answers: dict[str, str]


class QuizAnswerGradeResult(BaseModel):
    """study 모드 즉시채점 응답"""

    is_correct: bool
    correct_answer: str
    explanation: str
    score: float | None = Field(
        default=None, description="ESSAY 문항만 해당(0~100) — GPT 채점 점수"
    )
    feedback: str | None = Field(default=None, description="ESSAY 문항만 해당 — GPT 채점 코멘트")


class QuizSessionSubmit(BaseModel):
    answers: list[QuizAnswerSubmit] = Field(default_factory=list)


class QuizSessionRead(BaseModel):
    """진행 중/완료된 세션 메타 — 목록/이력 조회용"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    quiz_book_id: int
    user_id: int
    user_name: str | None = Field(
        default=None, description="응시자 이름 — 문제집 관리자가 전체 목록을 볼 때 표시용"
    )
    user_email: str | None = Field(default=None, description="응시자 이메일")
    mode: str
    status: str
    created_at: datetime
    submitted_at: datetime | None
    score: float | None
    correct_count: int | None
    total_count: int | None


class QuizSessionResult(QuizSessionRead):
    """세션 상세 — 문항별 답변(오답노트)까지 포함"""

    answers: list[QuizAnswerRecord]
