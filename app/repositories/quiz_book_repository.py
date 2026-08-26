from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.quiz_book import QuizBook
from app.models.quiz_book_question import QuizBookQuestion
from app.models.quiz_question import QuizQuestion


class QuizBookRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_project(self, project_id: int) -> list[QuizBook]:
        stmt = select(QuizBook).where(QuizBook.project_id == project_id)
        return list(self.db.scalars(stmt.order_by(QuizBook.id.desc())))

    def get(self, quiz_book_id: int) -> QuizBook | None:
        return self.db.get(QuizBook, quiz_book_id)

    def add(self, book: QuizBook) -> QuizBook:
        self.db.add(book)
        self.db.flush()
        return book

    def commit_refresh(self, *objs) -> None:
        self.db.commit()
        for obj in objs:
            self.db.refresh(obj)

    def delete(self, book: QuizBook) -> None:
        self.db.delete(book)
        self.db.commit()

    def list_questions(self, quiz_book_id: int) -> list[QuizQuestion]:
        """문제집 소속 문항을 order_no 순으로 돌려준다."""
        stmt = (
            select(QuizQuestion)
            .join(QuizBookQuestion, QuizBookQuestion.quiz_question_id == QuizQuestion.id)
            .where(QuizBookQuestion.quiz_book_id == quiz_book_id)
            .order_by(QuizBookQuestion.order_no)
        )
        return list(self.db.scalars(stmt))

    def list_links(self, quiz_book_id: int) -> list[QuizBookQuestion]:
        stmt = (
            select(QuizBookQuestion)
            .where(QuizBookQuestion.quiz_book_id == quiz_book_id)
            .order_by(QuizBookQuestion.order_no)
        )
        return list(self.db.scalars(stmt))

    def add_questions(self, quiz_book_id: int, question_ids: list[int]) -> None:
        """기존 순서 뒤에 이어 붙인다. 이미 편입된 문항은 건너뛴다."""
        existing_ids = {
            link.quiz_question_id for link in self.list_links(quiz_book_id)
        }
        next_order = self.db.scalar(
            select(func.coalesce(func.max(QuizBookQuestion.order_no), -1)).where(
                QuizBookQuestion.quiz_book_id == quiz_book_id
            )
        ) + 1
        for question_id in question_ids:
            if question_id in existing_ids:
                continue
            self.db.add(
                QuizBookQuestion(
                    quiz_book_id=quiz_book_id,
                    quiz_question_id=question_id,
                    order_no=next_order,
                )
            )
            existing_ids.add(question_id)
            next_order += 1
        self.db.commit()

    def question_in_book(self, quiz_book_id: int, question_id: int) -> bool:
        stmt = (
            select(QuizBookQuestion.id)
            .where(
                QuizBookQuestion.quiz_book_id == quiz_book_id,
                QuizBookQuestion.quiz_question_id == question_id,
            )
            .limit(1)
        )
        return self.db.scalar(stmt) is not None

    def remove_question(self, quiz_book_id: int, question_id: int) -> bool:
        link = self.db.scalar(
            select(QuizBookQuestion).where(
                QuizBookQuestion.quiz_book_id == quiz_book_id,
                QuizBookQuestion.quiz_question_id == question_id,
            )
        )
        if link is None:
            return False
        self.db.delete(link)
        self.db.commit()
        return True
