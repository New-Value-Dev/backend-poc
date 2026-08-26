from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.quiz_generation_job import QuizGenerationJob


class QuizGenerationJobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, job: QuizGenerationJob) -> QuizGenerationJob:
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get(self, job_id: int) -> QuizGenerationJob | None:
        return self.db.get(QuizGenerationJob, job_id)

    def list_by_project(self, project_id: int, *, limit: int = 20) -> list[QuizGenerationJob]:
        stmt = (
            select(QuizGenerationJob)
            .where(QuizGenerationJob.project_id == project_id)
            .order_by(QuizGenerationJob.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def commit_refresh(self, *objs) -> None:
        self.db.commit()
        for obj in objs:
            self.db.refresh(obj)
