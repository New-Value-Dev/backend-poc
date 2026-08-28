from __future__ import annotations

import logging
import math
import random
import re
import unicodedata
from datetime import datetime, timezone
from typing import NamedTuple

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.project import VISIBILITY_PUBLIC
from app.models.quiz_answer import QuizAnswer
from app.models.quiz_book import QuizBook
from app.models.quiz_question import (
    GENERATION_TYPE_MANUAL,
    QUESTION_TYPE_ESSAY,
    QUESTION_TYPE_SHORT_ANSWER,
    REVIEW_STATUS_DRAFT,
    QuizQuestion,
)
from app.models.quiz_session import SESSION_STATUS_SUBMITTED, QuizSession
from app.models.user import User
from app.repositories.embedding_repository import EmbeddingModelRepository
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.quiz_book_repository import QuizBookRepository
from app.repositories.quiz_question_repository import QuizQuestionRepository
from app.repositories.quiz_session_repository import QuizSessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.quiz import (
    QuizAnswerGradeResult,
    QuizAnswerRecord,
    QuizAnswerSubmit,
    QuizBookAssigneeRead,
    QuizBookCreate,
    QuizBookRead,
    QuizBookUpdate,
    QuizQuestionCreate,
    QuizQuestionPlay,
    QuizQuestionUpdate,
    QuizSessionResult,
)
from app.services.activity_service import Action, ActivityService, get_activity_service
from app.services.embedding.base import EmbeddingError
from app.services.embedding.factory import get_embedding_provider
from app.services.llm import LLMError, LLMProvider, get_llm_provider
from app.services.llm_usage_service import usage_sink

logger = logging.getLogger(__name__)


class QuizQuestionNotFoundError(Exception):
    def __init__(self, question_id: int) -> None:
        self.question_id = question_id
        super().__init__(f"Quiz question {question_id} not found")


class QuizBookNotFoundError(Exception):
    def __init__(self, quiz_book_id: int) -> None:
        self.quiz_book_id = quiz_book_id
        super().__init__(f"Quiz book {quiz_book_id} not found")


class QuizSessionNotFoundError(Exception):
    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Quiz session {session_id} not found")


class QuizSessionAlreadySubmittedError(Exception):
    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Quiz session {session_id} is already submitted")


class QuizBookLockedError(Exception):
    """응시 이력이 있는 문제집은 공정성을 위해 수정할 수 없다"""

    def __init__(self, quiz_book_id: int) -> None:
        self.quiz_book_id = quiz_book_id
        super().__init__(f"Quiz book {quiz_book_id} has sessions and cannot be modified")


class QuizBookForbiddenError(Exception):
    """이 문제집의 생성자도, 프로젝트 소유자도 아닌 사용자가 관리를 시도할 때"""

    def __init__(self, quiz_book_id: int) -> None:
        self.quiz_book_id = quiz_book_id
        super().__init__(f"No manage access to quiz book {quiz_book_id}")


class QuizAssigneeNotProjectMemberError(Exception):
    """지정하려는 사용자 중 지정할 수 없는 사람이 있을 때(비공개/초대 프로젝트: 활성 멤버가 아님,
    공개 프로젝트: 존재하는 활성 사용자가 아님)"""

    def __init__(self, user_ids: list[int]) -> None:
        self.user_ids = user_ids
        super().__init__(f"Users {user_ids} are not active members of this project")


class QuizBookSaveOutcome(NamedTuple):
    """문제집 생성/수정 결과 — notify_user_ids 는 이번에 새로 지정되어 알림을 받아야 할 사람"""

    book: QuizBookRead
    notify_user_ids: list[int]


def can_manage_quiz_book(book: QuizBook, user: User) -> bool:
    """문제집을 만든 사람, 프로젝트 소유자, 관리자만 설정/문제 구성을 바꿀 수 있다"""
    if user.role == "admin":
        return True
    if book.project.owner_id == user.id:
        return True
    return book.created_by_user_id == user.id


_DIGIT_GROUP_RE = re.compile(r"\d+")
_DATE_SEPARATOR_CHARS = set("년월일시분초.-/:")


def _normalize_short_answer(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = re.sub(r"\s+", "", s).lower()

    remainder = _DIGIT_GROUP_RE.sub("", s)
    if remainder and any(ch not in _DATE_SEPARATOR_CHARS for ch in remainder):
        return s  # 구분자 밖의 문자가 섞여 있으면 날짜/숫자 형태가 아니라고 보고 그대로 비교

    groups = _DIGIT_GROUP_RE.findall(s)
    if not groups:
        return s

    if len(groups) == 1 and len(groups[0]) in (6, 8):
        g = groups[0]
        groups = [g[:-4], g[-4:-2], g[-2:]]  # YYMMDD 또는 YYYYMMDD → [연,월,일]

    if len(groups) == 3 and len(groups[0]) == 2:
        groups[0] = "20" + groups[0]  # 연도 자리가 2자리면 20xx 로 간주

    return "-".join(g.zfill(2) for g in groups)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class QuizService:
    def __init__(
        self,
        questions: QuizQuestionRepository,
        books: QuizBookRepository,
        sessions: QuizSessionRepository,
        activity: ActivityService,
        embedding_models: EmbeddingModelRepository,
        project_members: ProjectMemberRepository,
        projects: ProjectRepository,
        users: UserRepository,
        settings: Settings,
        llm: LLMProvider,
    ) -> None:
        self.questions = questions
        self.books = books
        self.sessions = sessions
        self.activity = activity
        self.embedding_models = embedding_models
        self.project_members = project_members
        self.projects = projects
        self.users = users
        self.settings = settings
        self.llm = llm

    # ── 문제은행 ──

    def list_questions(self, project_id: int, **filters) -> list[QuizQuestion]:
        return self.questions.list_by_project(project_id, **filters)

    def get_question(self, question_id: int) -> QuizQuestion:
        question = self.questions.get(question_id)
        if question is None:
            raise QuizQuestionNotFoundError(question_id)
        return question

    def create_question(self, project_id: int, payload: QuizQuestionCreate) -> QuizQuestion:
        question = self.questions.add(
            QuizQuestion(
                project_id=project_id,
                source_document_id=payload.source_document_id,
                type=payload.type.value,
                text=payload.text,
                options=payload.options,
                correct_answer=payload.correct_answer,
                explanation=payload.explanation,
                difficulty=payload.difficulty.value,
                tags=payload.tags,
                source_location=payload.source_location,
                generation_type=GENERATION_TYPE_MANUAL,
                review_status=REVIEW_STATUS_DRAFT,
            )
        )
        self.questions.commit_refresh(question)
        self.activity.record(
            Action.QUIZ_QUESTION_CREATE,
            project_id=project_id,
            target_type="quiz_question",
            target_id=question.id,
            target_label=question.text[:80],
        )
        return question

    def update_question(self, question_id: int, payload: QuizQuestionUpdate) -> QuizQuestion:
        question = self.get_question(question_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(question, field, value.value if hasattr(value, "value") else value)
        self.questions.commit_refresh(question)
        return question

    def delete_question(self, question_id: int) -> None:
        question = self.get_question(question_id)
        project_id, label = question.project_id, question.text[:80]
        self.questions.delete(question)
        self.activity.record(
            Action.QUIZ_QUESTION_DELETE,
            project_id=project_id,
            target_type="quiz_question",
            target_id=question_id,
            target_label=label,
        )

    # ── 문제집 ──

    def list_books(self, project_id: int, current_user: User) -> list[QuizBookRead]:
        books = self.books.list_by_project(project_id)
        locked_ids = self.sessions.book_ids_with_sessions([b.id for b in books])
        return [self._to_read(b, b.id in locked_ids, current_user) for b in books]

    def get_book(self, quiz_book_id: int) -> QuizBook:
        """접근 검사/내부 로직용"""
        book = self.books.get(quiz_book_id)
        if book is None:
            raise QuizBookNotFoundError(quiz_book_id)
        return book

    def get_book_read(self, quiz_book_id: int, current_user: User) -> QuizBookRead:
        book = self.get_book(quiz_book_id)
        return self._to_read(book, self.sessions.has_sessions(book.id), current_user)

    def _to_read(self, book: QuizBook, has_sessions: bool, current_user: User) -> QuizBookRead:
        assignees = [
            QuizBookAssigneeRead(
                user_id=a.user_id,
                user_name=a.user.name if a.user else None,
                user_email=a.user.email if a.user else None,
                assigned_at=a.created_at,
            )
            for a in self.books.list_assignees(book.id)
        ]
        return QuizBookRead(
            id=book.id,
            project_id=book.project_id,
            title=book.title,
            description=book.description,
            source_document_ids=book.source_document_ids,
            passing_score=book.passing_score,
            time_limit_minutes=book.time_limit_minutes,
            shuffle_questions=book.shuffle_questions,
            shuffle_options=book.shuffle_options,
            allow_retake=book.allow_retake,
            reveal_answers=book.reveal_answers,
            due_at=book.due_at,
            assignees=assignees,
            has_sessions=has_sessions,
            created_by_user_id=book.created_by_user_id,
            can_manage=can_manage_quiz_book(book, current_user),
            created_at=book.created_at,
            updated_at=book.updated_at,
        )

    def _validate_assignees(self, project_id: int, user_ids: list[int]) -> None:
        if not user_ids:
            return
        project = self.projects.get(project_id)
        if project is not None and project.visibility == VISIBILITY_PUBLIC:
            valid_ids = self.users.list_active_ids(set(user_ids))
            invalid = [uid for uid in user_ids if uid not in valid_ids]
        else:
            invalid = [
                uid
                for uid in user_ids
                if self.project_members.get_active(project_id, uid) is None
            ]
        if invalid:
            raise QuizAssigneeNotProjectMemberError(invalid)

    def create_book(
        self, project_id: int, payload: QuizBookCreate, current_user: User
    ) -> QuizBookSaveOutcome:
        self._validate_assignees(project_id, payload.assignee_user_ids)
        book = self.books.add(
            QuizBook(
                project_id=project_id,
                created_by_user_id=current_user.id,
                title=payload.title,
                description=payload.description,
                source_document_ids=payload.source_document_ids,
                passing_score=payload.passing_score,
                time_limit_minutes=payload.time_limit_minutes,
                shuffle_questions=payload.shuffle_questions,
                shuffle_options=payload.shuffle_options,
                allow_retake=payload.allow_retake,
                reveal_answers=payload.reveal_answers,
                due_at=payload.due_at,
            )
        )
        self.books.commit_refresh(book)
        notify_user_ids = self.books.set_assignees(
            book.id, payload.assignee_user_ids, assigned_by=current_user.id
        )
        self.activity.record(
            Action.QUIZ_BOOK_CREATE,
            project_id=project_id,
            target_type="quiz_book",
            target_id=book.id,
            target_label=book.title,
        )
        return QuizBookSaveOutcome(self._to_read(book, False, current_user), notify_user_ids)

    def _ensure_unlocked(self, quiz_book_id: int) -> None:
        if self.sessions.has_sessions(quiz_book_id):
            raise QuizBookLockedError(quiz_book_id)

    def update_book(
        self, quiz_book_id: int, payload: QuizBookUpdate, current_user: User
    ) -> QuizBookSaveOutcome:
        book = self.get_book(quiz_book_id)
        self._ensure_unlocked(quiz_book_id)
        data = payload.model_dump(exclude_unset=True)
        assignee_user_ids = data.pop("assignee_user_ids", None)
        for field, value in data.items():
            setattr(book, field, value)
        self.books.commit_refresh(book)

        notify_user_ids: list[int] = []
        if assignee_user_ids is not None:
            self._validate_assignees(book.project_id, assignee_user_ids)
            notify_user_ids = self.books.set_assignees(
                book.id, assignee_user_ids, assigned_by=current_user.id
            )

        self.activity.record(
            Action.QUIZ_BOOK_UPDATE,
            project_id=book.project_id,
            target_type="quiz_book",
            target_id=book.id,
            target_label=book.title,
        )
        return QuizBookSaveOutcome(self._to_read(book, False, current_user), notify_user_ids)

    def delete_book(self, quiz_book_id: int) -> None:
        book = self.get_book(quiz_book_id)
        project_id, label = book.project_id, book.title
        self.books.delete(book)
        self.activity.record(
            Action.QUIZ_BOOK_DELETE,
            project_id=project_id,
            target_type="quiz_book",
            target_id=quiz_book_id,
            target_label=label,
        )

    def duplicate_book(self, quiz_book_id: int, current_user: User) -> QuizBookRead:
        original = self.get_book(quiz_book_id)
        copy = self.books.add(
            QuizBook(
                project_id=original.project_id,
                created_by_user_id=current_user.id,
                title=original.title,
                description=original.description,
                source_document_ids=original.source_document_ids,
                passing_score=original.passing_score,
                time_limit_minutes=original.time_limit_minutes,
                shuffle_questions=original.shuffle_questions,
                shuffle_options=original.shuffle_options,
                allow_retake=original.allow_retake,
                reveal_answers=original.reveal_answers,
                due_at=original.due_at,
            )
        )
        question_ids = [link.quiz_question_id for link in self.books.list_links(quiz_book_id)]
        self.books.add_questions(copy.id, question_ids)
        self.books.commit_refresh(copy)
        self.activity.record(
            Action.QUIZ_BOOK_CREATE,
            project_id=original.project_id,
            target_type="quiz_book",
            target_id=copy.id,
            target_label=copy.title,
            meta={"duplicated_from": quiz_book_id},
        )
        return self._to_read(copy, False, current_user)

    def list_book_questions(self, quiz_book_id: int) -> list[QuizQuestion]:
        self.get_book(quiz_book_id)
        return self.books.list_questions(quiz_book_id)

    def add_questions_to_book(self, quiz_book_id: int, question_ids: list[int]) -> list[QuizQuestion]:
        self.get_book(quiz_book_id)
        self._ensure_unlocked(quiz_book_id)
        self.books.add_questions(quiz_book_id, question_ids)
        return self.books.list_questions(quiz_book_id)

    def remove_question_from_book(self, quiz_book_id: int, question_id: int) -> None:
        self.get_book(quiz_book_id)
        self._ensure_unlocked(quiz_book_id)
        self.books.remove_question(quiz_book_id, question_id)

    # ── 응시 ──

    def start_session(
        self, quiz_book_id: int, user_id: int, mode: str
    ) -> tuple[QuizSession, list[QuizQuestionPlay], list[QuizAnswerRecord], bool, dict[str, str]]:
        """진행중(IN_PROGRESS) 세션이 있으면 새로 만들지 않고 그걸 재개"""
        book = self.get_book(quiz_book_id)

        existing = self.sessions.get_in_progress(quiz_book_id, user_id)
        if existing is not None and existing.question_order:
            questions = self._questions_in_order(existing.question_order)
            answers = self.sessions.list_answers(existing.id)
            play_list = [QuizQuestionPlay.model_validate(q) for q in questions]
            return (
                existing,
                play_list,
                self._to_records(answers, book.reveal_answers),
                True,
                dict(existing.draft_answers or {}),
            )
        if existing is not None:
            # 문제집에 문항이 하나도 없던 시점에 시작된 죽은 세션
            self.sessions.delete(existing)

        questions = self.books.list_questions(quiz_book_id)
        if book.shuffle_questions:
            questions = questions.copy()
            random.shuffle(questions)
        # shuffle_options 는 정답 index 매핑이 꼬이지 않도록 백엔드에서 섞지 않는다
        session = self.sessions.add(
            QuizSession(
                quiz_book_id=quiz_book_id,
                user_id=user_id,
                mode=mode,
                question_order=[q.id for q in questions],
            )
        )
        play_list = [QuizQuestionPlay.model_validate(q) for q in questions]
        return session, play_list, [], False, {}

    def save_draft_answer(
        self, quiz_book_id: int, session_id: int, user_id: int, question_id: int, user_answer: str
    ) -> dict[str, str]:
        """exam 모드 자동저장"""
        session = self._get_owned_session(quiz_book_id, session_id, user_id)
        if session.status == SESSION_STATUS_SUBMITTED:
            raise QuizSessionAlreadySubmittedError(session_id)
        if not self.books.question_in_book(session.quiz_book_id, question_id):
            raise QuizQuestionNotFoundError(question_id)
        draft = dict(session.draft_answers or {})
        draft[str(question_id)] = user_answer
        session.draft_answers = draft
        self.sessions.commit_refresh(session)
        return draft

    def _questions_in_order(self, question_ids: list[int]) -> list[QuizQuestion]:
        by_id = {q.id: q for q in self.questions.get_many(question_ids)}
        return [by_id[qid] for qid in question_ids if qid in by_id]

    def _get_owned_session(self, quiz_book_id: int, session_id: int, user_id: int) -> QuizSession:
        session = self.sessions.get(session_id)
        if (
            session is None
            or session.user_id != user_id
            or session.quiz_book_id != quiz_book_id
        ):
            raise QuizSessionNotFoundError(session_id)
        return session

    def _grade(self, question: QuizQuestion, user_answer: str) -> tuple[bool, float | None]:
        """정답 여부와 유사도 점수를 함께 돌려준다"""
        correct = question.correct_answer.strip()
        given = (user_answer or "").strip()
        if question.type != QUESTION_TYPE_SHORT_ANSWER:
            return given == correct, None
        if given.lower() == correct.lower():
            return True, None
        if _normalize_short_answer(given) == _normalize_short_answer(correct):
            return True, None
        similarity = self._short_answer_similarity(correct, given)
        if similarity is None:
            return False, None  # 임베딩 불가 — 완전일치까지만 인정
        if similarity >= self.settings.quiz_short_answer_similarity_high:
            return True, similarity
        if similarity < self.settings.quiz_short_answer_similarity_low:
            return False, similarity
        # 애매한 구간 — 문장 임베딩은 숫자·사실 정확성에 약해서 오답과 간격이 좁을 수 있다.
        # GPT에게 사실관계까지 보고 최종 판정하게 한다.
        return self._judge_short_answer(question, correct, given), similarity

    def _judge_short_answer(self, question: QuizQuestion, correct: str, given: str) -> bool:
        """GPT 최종 판정. 실패하면 확신할 수 없으므로 보수적으로 오답 처리한다."""
        try:
            return self.llm.judge_short_answer(
                question=question.text, correct_answer=correct, user_answer=given
            )
        except LLMError as exc:
            logger.warning("단답형 GPT 판정 실패, 오답 처리합니다: %s", exc)
            return False

    def _short_answer_similarity(self, correct: str, given: str) -> float | None:
        """활성 임베딩 모델이 없거나 로드에 실패하면 None"""
        if not correct or not given:
            return None
        active = self.embedding_models.get_active()
        if active is None:
            return None
        try:
            provider = get_embedding_provider(self.settings, active)
            vec_correct = provider.embed_query(correct)
            vec_given = provider.embed_query(given)
        except EmbeddingError as exc:
            logger.warning("단답형 유사도 계산 실패, 완전일치로만 채점합니다: %s", exc)
            return None
        return _cosine_similarity(vec_correct, vec_given)

    def _grade_essay(
        self, question: QuizQuestion, user_answer: str, passing_score: int
    ) -> tuple[bool, float | None, str | None]:
        """GPT로 0~100점 채점"""
        given = (user_answer or "").strip()
        if not given:
            return False, 0.0, "답안이 비어 있습니다."
        try:
            result = self.llm.grade_essay(
                question=question.text,
                model_answer=question.correct_answer,
                rubric=question.explanation,
                user_answer=given,
            )
        except LLMError as exc:
            logger.warning("서술형 채점 실패: %s", exc)
            return False, None, "채점 중 오류가 발생했습니다. 다시 시도해 주세요."
        return result.score >= passing_score, result.score, result.feedback

    def _record_answer(
        self, session: QuizSession, question: QuizQuestion, user_answer: str, book: QuizBook
    ) -> QuizAnswer:
        similarity: float | None = None
        score: float | None = None
        feedback: str | None = None
        if question.type == QUESTION_TYPE_ESSAY:
            is_correct, score, feedback = self._grade_essay(question, user_answer, book.passing_score)
        else:
            is_correct, similarity = self._grade(question, user_answer)
        return self.sessions.upsert_answer(
            QuizAnswer(
                session_id=session.id,
                question_id=question.id,
                question_text=question.text,
                options=question.options,
                correct_answer=question.correct_answer,
                explanation=question.explanation,
                user_answer=user_answer,
                is_correct=is_correct,
                similarity_score=similarity,
                score=score,
                feedback=feedback,
            )
        )

    def grade_answer(
        self, quiz_book_id: int, session_id: int, user_id: int, question_id: int, user_answer: str
    ) -> QuizAnswerGradeResult:
        session = self._get_owned_session(quiz_book_id, session_id, user_id)
        if session.status == SESSION_STATUS_SUBMITTED:
            raise QuizSessionAlreadySubmittedError(session_id)
        book = self.get_book(session.quiz_book_id)
        question = self.get_question(question_id)
        if not self.books.question_in_book(session.quiz_book_id, question_id):
            raise QuizQuestionNotFoundError(question_id)
        answer = self._record_answer(session, question, user_answer, book)
        return QuizAnswerGradeResult(
            is_correct=answer.is_correct,
            correct_answer=question.correct_answer,
            explanation=question.explanation,
            score=answer.score,
            feedback=answer.feedback,
        )

    def submit_session(
        self, quiz_book_id: int, session_id: int, user_id: int, answers: list[QuizAnswerSubmit]
    ) -> QuizSessionResult:
        session = self._get_owned_session(quiz_book_id, session_id, user_id)
        if session.status == SESSION_STATUS_SUBMITTED:
            raise QuizSessionAlreadySubmittedError(session_id)
        book = self.get_book(session.quiz_book_id)

        for item in answers:
            question = self.questions.get(item.question_id)
            if question is None or not self.books.question_in_book(book.id, question.id):
                continue
            self._record_answer(session, question, item.user_answer, book)

        all_answers = self.sessions.list_answers(session_id)
        total_count = len(all_answers)
        correct_count = sum(1 for a in all_answers if a.is_correct)
        session.status = SESSION_STATUS_SUBMITTED
        session.submitted_at = datetime.now(timezone.utc)
        session.correct_count = correct_count
        session.total_count = total_count
        session.score = round(correct_count / total_count * 100, 2) if total_count else 0.0
        self.sessions.commit_refresh(session)

        self.activity.record(
            Action.QUIZ_SESSION_SUBMIT,
            project_id=book.project_id,
            target_type="quiz_book",
            target_id=book.id,
            target_label=book.title,
            meta={"session_id": session.id, "score": session.score},
        )
        return self._build_session_result(session, book, all_answers)

    def get_session_detail(
        self, quiz_book_id: int, session_id: int, viewer: User
    ) -> QuizSessionResult:
        """본인 세션이거나, 문제집 관리자면 다른 사람 세션도 상세를 볼 수 있다"""
        session = self.sessions.get(session_id)
        if session is None or session.quiz_book_id != quiz_book_id:
            raise QuizSessionNotFoundError(session_id)
        book = self.get_book(session.quiz_book_id)
        is_manager = can_manage_quiz_book(book, viewer)
        if session.user_id != viewer.id and not is_manager:
            raise QuizSessionNotFoundError(session_id)  # 남의 세션은 존재를 숨긴다(기존 패턴과 일관)
        answers = self.sessions.list_answers(session_id)
        reveal = True if is_manager else book.reveal_answers
        return self._build_session_result(session, book, answers, reveal=reveal)

    def get_book_sessions(
        self, quiz_book_id: int, viewer: User, status: str | None = None
    ) -> list[QuizSession]:
        """문제집 관리자는 전체 응시자, 그 외는 본인 응시 이력만"""
        book = self.get_book(quiz_book_id)
        if can_manage_quiz_book(book, viewer):
            return self.sessions.list_by_book(quiz_book_id, status=status)
        return self.sessions.list_by_book(quiz_book_id, user_id=viewer.id, status=status)

    def get_project_sessions(
        self, project_id: int, user_id: int, status: str | None = None
    ) -> list[QuizSession]:
        return self.sessions.list_by_project(project_id, user_id=user_id, status=status)

    def _to_records(self, answers: list[QuizAnswer], reveal: bool) -> list[QuizAnswerRecord]:
        return [
            QuizAnswerRecord(
                question_id=a.question_id,
                question_text=a.question_text,
                options=a.options,
                user_answer=a.user_answer,
                is_correct=a.is_correct,
                correct_answer=a.correct_answer if reveal else None,
                explanation=a.explanation if reveal else None,
                score=a.score if reveal else None,
                feedback=a.feedback if reveal else None,
            )
            for a in answers
        ]

    def _build_session_result(
        self,
        session: QuizSession,
        book: QuizBook,
        answers: list[QuizAnswer],
        *,
        reveal: bool | None = None,
    ) -> QuizSessionResult:
        records = self._to_records(answers, book.reveal_answers if reveal is None else reveal)
        return QuizSessionResult(
            id=session.id,
            quiz_book_id=session.quiz_book_id,
            user_id=session.user_id,
            user_name=session.user_name,
            user_email=session.user_email,
            mode=session.mode,
            status=session.status,
            created_at=session.created_at,
            submitted_at=session.submitted_at,
            score=session.score,
            correct_count=session.correct_count,
            total_count=session.total_count,
            answers=records,
        )


def get_quiz_service(
    db: Session = Depends(get_db),
    activity: ActivityService = Depends(get_activity_service),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> QuizService:
    return QuizService(
        QuizQuestionRepository(db),
        QuizBookRepository(db),
        QuizSessionRepository(db),
        activity,
        EmbeddingModelRepository(db),
        ProjectMemberRepository(db),
        ProjectRepository(db),
        UserRepository(db),
        settings,
        # project_id 는 요청마다 어느 quiz book 을 채점하는지에 따라 달라지는데 provider는
        # 요청당 한 번만(DI 시점) 만들어져 여기선 알 수 없다 — user_id만 채우고 None으로 둔다.
        get_llm_provider(
            settings, on_usage=usage_sink(db, user_id=current_user.id, project_id=None)
        ),
    )
