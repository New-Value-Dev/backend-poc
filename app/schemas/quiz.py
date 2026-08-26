from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class QuizQuestionType(str, Enum):
    SINGLE_CHOICE = "SINGLE_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"
    SHORT_ANSWER = "SHORT_ANSWER"


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
    has_sessions: bool = Field(
        description="true면 응시 이력이 있어 설정/문제 구성 수정이 409로 막힌다 — /duplicate로 복제할 것"
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


class QuizSessionStartResponse(BaseModel):
    """세션 시작 응답 — 정답이 빠진 문항 목록 + session_id"""

    session_id: int
    mode: str
    questions: list[QuizQuestionPlay]


class QuizAnswerSubmit(BaseModel):
    question_id: int
    user_answer: str


class QuizAnswerGradeResult(BaseModel):
    """study 모드 즉시채점 응답"""

    is_correct: bool
    correct_answer: str
    explanation: str


class QuizSessionSubmit(BaseModel):
    answers: list[QuizAnswerSubmit] = Field(default_factory=list)


class QuizAnswerRecord(BaseModel):
    """제출 결과의 문항별 답변 1건"""

    question_id: int | None
    question_text: str
    options: list[str] | None
    user_answer: str
    is_correct: bool
    correct_answer: str | None
    explanation: str | None


class QuizSessionRead(BaseModel):
    """진행 중/완료된 세션 메타 — 목록/이력 조회용"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    quiz_book_id: int
    user_id: int
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
