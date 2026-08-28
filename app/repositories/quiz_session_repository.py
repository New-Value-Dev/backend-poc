from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.quiz_answer import QuizAnswer
from app.models.quiz_book import QuizBook
from app.models.quiz_session import SESSION_STATUS_IN_PROGRESS, QuizSession


class QuizSessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, session: QuizSession) -> QuizSession:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get(self, session_id: int) -> QuizSession | None:
        return self.db.get(QuizSession, session_id)

    def delete(self, session: QuizSession) -> None:
        self.db.delete(session)
        self.db.commit()

    def get_in_progress(self, quiz_book_id: int, user_id: int) -> QuizSession | None:
        """이 유저가 이 문제집에 진행중인 세션이 있으면 그것을 돌려준다"""
        stmt = (
            select(QuizSession)
            .where(
                QuizSession.quiz_book_id == quiz_book_id,
                QuizSession.user_id == user_id,
                QuizSession.status == SESSION_STATUS_IN_PROGRESS,
            )
            .order_by(QuizSession.id.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_by_book(
        self, quiz_book_id: int, *, user_id: int | None = None, status: str | None = None
    ) -> list[QuizSession]:
        stmt = (
            select(QuizSession)
            .options(joinedload(QuizSession.user))
            .where(QuizSession.quiz_book_id == quiz_book_id)
        )
        if user_id is not None:
            stmt = stmt.where(QuizSession.user_id == user_id)
        if status is not None:
            stmt = stmt.where(QuizSession.status == status)
        return list(self.db.scalars(stmt.order_by(QuizSession.id.desc())))

    def list_by_project(
        self, project_id: int, *, user_id: int | None = None, status: str | None = None
    ) -> list[QuizSession]:
        stmt = (
            select(QuizSession)
            .options(joinedload(QuizSession.user))
            .join(QuizBook, QuizBook.id == QuizSession.quiz_book_id)
            .where(QuizBook.project_id == project_id)
        )
        if user_id is not None:
            stmt = stmt.where(QuizSession.user_id == user_id)
        if status is not None:
            stmt = stmt.where(QuizSession.status == status)
        return list(self.db.scalars(stmt.order_by(QuizSession.id.desc())))

    def has_sessions(self, quiz_book_id: int) -> bool:
        stmt = select(QuizSession.id).where(QuizSession.quiz_book_id == quiz_book_id).limit(1)
        return self.db.scalar(stmt) is not None

    def book_ids_with_sessions(self, quiz_book_ids: list[int]) -> set[int]:
        """목록 조회에서 book마다 따로 쿼리하지 않도록 한 번에 배치 조회."""
        if not quiz_book_ids:
            return set()
        stmt = (
            select(QuizSession.quiz_book_id)
            .where(QuizSession.quiz_book_id.in_(quiz_book_ids))
            .distinct()
        )
        return set(self.db.scalars(stmt))

    def commit_refresh(self, *objs) -> None:
        self.db.commit()
        for obj in objs:
            self.db.refresh(obj)

    def get_answer(self, session_id: int, question_id: int) -> QuizAnswer | None:
        stmt = select(QuizAnswer).where(
            QuizAnswer.session_id == session_id, QuizAnswer.question_id == question_id
        )
        return self.db.scalar(stmt)

    def upsert_answer(self, answer: QuizAnswer) -> QuizAnswer:
        existing = self.get_answer(answer.session_id, answer.question_id)
        if existing is not None:
            existing.user_answer = answer.user_answer
            existing.is_correct = answer.is_correct
            existing.question_text = answer.question_text
            existing.options = answer.options
            existing.correct_answer = answer.correct_answer
            existing.explanation = answer.explanation
            existing.similarity_score = answer.similarity_score
            existing.score = answer.score
            existing.feedback = answer.feedback
            self.db.commit()
            self.db.refresh(existing)
            return existing
        self.db.add(answer)
        self.db.commit()
        self.db.refresh(answer)
        return answer

    def list_answers(self, session_id: int) -> list[QuizAnswer]:
        stmt = select(QuizAnswer).where(QuizAnswer.session_id == session_id).order_by(QuizAnswer.id)
        return list(self.db.scalars(stmt))
