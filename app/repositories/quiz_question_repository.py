from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.quiz_question import QuizQuestion


class QuizQuestionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_project(
        self,
        project_id: int,
        *,
        document_id: int | None = None,
        difficulty: str | None = None,
        type: str | None = None,
        review_status: str | None = None,
        q: str | None = None,
    ) -> list[QuizQuestion]:
        stmt = (
            select(QuizQuestion)
            .options(joinedload(QuizQuestion.source_document))
            .where(QuizQuestion.project_id == project_id)
        )
        if document_id is not None:
            stmt = stmt.where(QuizQuestion.source_document_id == document_id)
        if difficulty is not None:
            stmt = stmt.where(QuizQuestion.difficulty == difficulty)
        if type is not None:
            stmt = stmt.where(QuizQuestion.type == type)
        if review_status is not None:
            stmt = stmt.where(QuizQuestion.review_status == review_status)
        if q is not None:
            stmt = stmt.where(QuizQuestion.text.ilike(f"%{q}%"))
        return list(self.db.scalars(stmt.order_by(QuizQuestion.id.desc())))

    def get(self, question_id: int) -> QuizQuestion | None:
        return self.db.get(QuizQuestion, question_id)

    def get_many(self, question_ids: list[int]) -> list[QuizQuestion]:
        if not question_ids:
            return []
        return list(
            self.db.scalars(select(QuizQuestion).where(QuizQuestion.id.in_(question_ids)))
        )

    def list_recent_texts(
        self, project_id: int, *, document_ids: list[int] | None = None, limit: int = 50
    ) -> list[str]:
        """중복 회피 프롬프트에 넣을 기존 문항 본문(최신순).

        같은 문서에서 뽑은 문항이 가장 중복될 확률이 높으므로 document_ids 가 주어지면
        그 문서 소속 문항을 우선 본다.
        """
        stmt = select(QuizQuestion.text).where(QuizQuestion.project_id == project_id)
        if document_ids:
            stmt = stmt.where(QuizQuestion.source_document_id.in_(document_ids))
        stmt = stmt.order_by(QuizQuestion.id.desc()).limit(limit)
        return [t for t in self.db.scalars(stmt) if t]

    def add(self, question: QuizQuestion) -> QuizQuestion:
        self.db.add(question)
        self.db.flush()
        return question

    def commit_refresh(self, *objs) -> None:
        self.db.commit()
        for obj in objs:
            self.db.refresh(obj)

    def delete(self, question: QuizQuestion) -> None:
        self.db.delete(question)
        self.db.commit()
