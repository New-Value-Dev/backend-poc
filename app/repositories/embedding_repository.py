from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chunk_embedding import ChunkEmbedding
from app.models.document_chunk import DocumentChunk
from app.models.embedding_job import EmbeddingJob
from app.models.embedding_model import EmbeddingModel


class EmbeddingModelRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[EmbeddingModel]:
        return list(self.db.scalars(select(EmbeddingModel).order_by(EmbeddingModel.id)))

    def get(self, model_id: int) -> EmbeddingModel | None:
        return self.db.get(EmbeddingModel, model_id)

    def get_by_key(self, model_key: str) -> EmbeddingModel | None:
        return self.db.scalar(
            select(EmbeddingModel).where(EmbeddingModel.model_key == model_key)
        )

    def get_active(self) -> EmbeddingModel | None:
        return self.db.scalar(select(EmbeddingModel).where(EmbeddingModel.is_active.is_(True)))

    def add(self, model: EmbeddingModel) -> EmbeddingModel:
        self.db.add(model)
        self.db.flush()
        return model

    def activate(self, model: EmbeddingModel) -> EmbeddingModel:
        """다른 모델을 전부 비활성화하고 이 모델만 활성화한다."""
        for other in self.db.scalars(
            select(EmbeddingModel).where(EmbeddingModel.is_active.is_(True))
        ):
            other.is_active = False
        model.is_active = True
        if model.status == "TEST":
            model.status = "ACTIVE"
        self.db.commit()
        self.db.refresh(model)
        return model


class ChunkEmbeddingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def bulk_add(self, rows: list[ChunkEmbedding]) -> None:
        if not rows:
            return
        self.db.add_all(rows)
        self.db.commit()

    def existing_chunk_ids(self, chunk_ids: list[int], embedding_model_id: int) -> set[int]:
        """재시도 시 이미 임베딩된 chunk_id를 걸러내 멱등성을 확보한다."""
        if not chunk_ids:
            return set()
        rows = self.db.scalars(
            select(ChunkEmbedding.chunk_id).where(
                ChunkEmbedding.embedding_model_id == embedding_model_id,
                ChunkEmbedding.chunk_id.in_(chunk_ids),
            )
        )
        return set(rows)

    def count_all_chunks(self) -> int:
        """reembed 작업의 target_count(진행률 분모)용 — 전체 document_chunks 개수."""
        return self.db.scalar(select(func.count()).select_from(DocumentChunk)) or 0


class EmbeddingJobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, job_id: int) -> EmbeddingJob | None:
        return self.db.get(EmbeddingJob, job_id)

    def add(self, job: EmbeddingJob) -> EmbeddingJob:
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job
