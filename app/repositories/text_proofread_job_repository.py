from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.text_proofread_job import TextProofreadJob


class TextProofreadJobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, job: TextProofreadJob) -> TextProofreadJob:
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get(self, job_id: int) -> TextProofreadJob | None:
        return self.db.get(TextProofreadJob, job_id)

    def list_by_user(self, user_id: int, *, limit: int = 20) -> list[TextProofreadJob]:
        stmt = (
            select(TextProofreadJob)
            .where(TextProofreadJob.user_id == user_id)
            .order_by(TextProofreadJob.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
