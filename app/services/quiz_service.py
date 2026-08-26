from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.quiz_answer import QuizAnswer
from app.models.quiz_book import QuizBook
from app.models.quiz_question import (
    GENERATION_TYPE_MANUAL,
    QUESTION_TYPE_SHORT_ANSWER,
    REVIEW_STATUS_DRAFT,
    QuizQuestion,
)
from app.models.quiz_session import SESSION_STATUS_SUBMITTED, QuizSession
from app.repositories.quiz_book_repository import QuizBookRepository
from app.repositories.quiz_question_repository import QuizQuestionRepository
from app.repositories.quiz_session_repository import QuizSessionRepository
from app.schemas.quiz import (
    QuizAnswerGradeResult,
    QuizAnswerRecord,
    QuizAnswerSubmit,
    QuizBookCreate,
    QuizBookRead,
    QuizBookUpdate,
    QuizQuestionCreate,
    QuizQuestionPlay,
    QuizQuestionUpdate,
    QuizSessionResult,
)
from app.services.activity_service import Action, ActivityService, get_activity_service


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


def _grade(question: QuizQuestion, user_answer: str) -> bool:
    correct = question.correct_answer.strip()
    given = (user_answer or "").strip()
    if question.type == QUESTION_TYPE_SHORT_ANSWER:
        return given.lower() == correct.lower()
    return given == correct


class QuizService:
    def __init__(
        self,
        questions: QuizQuestionRepository,
        books: QuizBookRepository,
        sessions: QuizSessionRepository,
        activity: ActivityService,
    ) -> None:
        self.questions = questions
        self.books = books
        self.sessions = sessions
        self.activity = activity

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

    def list_books(self, project_id: int) -> list[QuizBookRead]:
        books = self.books.list_by_project(project_id)
        locked_ids = self.sessions.book_ids_with_sessions([b.id for b in books])
        return [self._to_read(b, b.id in locked_ids) for b in books]

    def get_book(self, quiz_book_id: int) -> QuizBook:
        """접근 검사/내부 로직용"""
        book = self.books.get(quiz_book_id)
        if book is None:
            raise QuizBookNotFoundError(quiz_book_id)
        return book

    def get_book_read(self, quiz_book_id: int) -> QuizBookRead:
        book = self.get_book(quiz_book_id)
        return self._to_read(book, self.sessions.has_sessions(book.id))

    def _to_read(self, book: QuizBook, has_sessions: bool) -> QuizBookRead:
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
            has_sessions=has_sessions,
            created_at=book.created_at,
            updated_at=book.updated_at,
        )

    def create_book(self, project_id: int, payload: QuizBookCreate) -> QuizBookRead:
        book = self.books.add(
            QuizBook(
                project_id=project_id,
                title=payload.title,
                description=payload.description,
                source_document_ids=payload.source_document_ids,
                passing_score=payload.passing_score,
                time_limit_minutes=payload.time_limit_minutes,
                shuffle_questions=payload.shuffle_questions,
                shuffle_options=payload.shuffle_options,
                allow_retake=payload.allow_retake,
                reveal_answers=payload.reveal_answers,
            )
        )
        self.books.commit_refresh(book)
        self.activity.record(
            Action.QUIZ_BOOK_CREATE,
            project_id=project_id,
            target_type="quiz_book",
            target_id=book.id,
            target_label=book.title,
        )
        return self._to_read(book, False)

    def _ensure_unlocked(self, quiz_book_id: int) -> None:
        if self.sessions.has_sessions(quiz_book_id):
            raise QuizBookLockedError(quiz_book_id)

    def update_book(self, quiz_book_id: int, payload: QuizBookUpdate) -> QuizBookRead:
        book = self.get_book(quiz_book_id)
        self._ensure_unlocked(quiz_book_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(book, field, value)
        self.books.commit_refresh(book)
        self.activity.record(
            Action.QUIZ_BOOK_UPDATE,
            project_id=book.project_id,
            target_type="quiz_book",
            target_id=book.id,
            target_label=book.title,
        )
        return self._to_read(book, False)

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

    def duplicate_book(self, quiz_book_id: int) -> QuizBookRead:
        original = self.get_book(quiz_book_id)
        copy = self.books.add(
            QuizBook(
                project_id=original.project_id,
                title=original.title,
                description=original.description,
                source_document_ids=original.source_document_ids,
                passing_score=original.passing_score,
                time_limit_minutes=original.time_limit_minutes,
                shuffle_questions=original.shuffle_questions,
                shuffle_options=original.shuffle_options,
                allow_retake=original.allow_retake,
                reveal_answers=original.reveal_answers,
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
        return self._to_read(copy, False)

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
    ) -> tuple[QuizSession, list[QuizQuestionPlay]]:
        book = self.get_book(quiz_book_id)
        questions = self.books.list_questions(quiz_book_id)
        if book.shuffle_questions:
            questions = questions.copy()
            random.shuffle(questions)
        # shuffle_options 는 정답 index 매핑이 꼬이지 않도록 백엔드에서 섞지 않는다
        session = self.sessions.add(
            QuizSession(quiz_book_id=quiz_book_id, user_id=user_id, mode=mode)
        )
        play_list = [QuizQuestionPlay.model_validate(q) for q in questions]
        return session, play_list

    def _get_owned_session(self, quiz_book_id: int, session_id: int, user_id: int) -> QuizSession:
        session = self.sessions.get(session_id)
        if (
            session is None
            or session.user_id != user_id
            or session.quiz_book_id != quiz_book_id
        ):
            raise QuizSessionNotFoundError(session_id)
        return session

    def _record_answer(self, session: QuizSession, question: QuizQuestion, user_answer: str) -> QuizAnswer:
        is_correct = _grade(question, user_answer)
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
            )
        )

    def grade_answer(
        self, quiz_book_id: int, session_id: int, user_id: int, question_id: int, user_answer: str
    ) -> QuizAnswerGradeResult:
        session = self._get_owned_session(quiz_book_id, session_id, user_id)
        if session.status == SESSION_STATUS_SUBMITTED:
            raise QuizSessionAlreadySubmittedError(session_id)
        question = self.get_question(question_id)
        if not self.books.question_in_book(session.quiz_book_id, question_id):
            raise QuizQuestionNotFoundError(question_id)
        answer = self._record_answer(session, question, user_answer)
        return QuizAnswerGradeResult(
            is_correct=answer.is_correct,
            correct_answer=question.correct_answer,
            explanation=question.explanation,
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
            self._record_answer(session, question, item.user_answer)

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

    def get_session_detail(self, quiz_book_id: int, session_id: int, user_id: int) -> QuizSessionResult:
        session = self._get_owned_session(quiz_book_id, session_id, user_id)
        book = self.get_book(session.quiz_book_id)
        answers = self.sessions.list_answers(session_id)
        return self._build_session_result(session, book, answers)

    def get_book_sessions(self, quiz_book_id: int) -> list[QuizSession]:
        self.get_book(quiz_book_id)
        return self.sessions.list_by_book(quiz_book_id)

    def get_project_sessions(self, project_id: int, user_id: int) -> list[QuizSession]:
        return self.sessions.list_by_project(project_id, user_id=user_id)

    def _build_session_result(
        self, session: QuizSession, book: QuizBook, answers: list[QuizAnswer]
    ) -> QuizSessionResult:
        reveal = book.reveal_answers
        records = [
            QuizAnswerRecord(
                question_id=a.question_id,
                question_text=a.question_text,
                options=a.options,
                user_answer=a.user_answer,
                is_correct=a.is_correct,
                correct_answer=a.correct_answer if reveal else None,
                explanation=a.explanation if reveal else None,
            )
            for a in answers
        ]
        return QuizSessionResult(
            id=session.id,
            quiz_book_id=session.quiz_book_id,
            user_id=session.user_id,
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
) -> QuizService:
    return QuizService(
        QuizQuestionRepository(db),
        QuizBookRepository(db),
        QuizSessionRepository(db),
        activity,
    )
