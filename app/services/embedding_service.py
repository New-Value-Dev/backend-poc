"""임베딩 파이프라인 오케스트레이션 + EmbeddingLab(모델 목록/활성화/재임베딩) 서비스"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal, get_db
from app.models.chunk_embedding import ChunkEmbedding
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.embedding_job import EmbeddingJob
from app.models.embedding_model import EmbeddingModel
from app.repositories.document_repository import DocumentVersionRepository
from app.repositories.embedding_repository import (
    ChunkEmbeddingRepository,
    EmbeddingJobRepository,
    EmbeddingModelRepository,
)
from app.services.embedding.factory import get_embedding_provider

logger = logging.getLogger(__name__)


class EmbeddingModelNotFoundError(Exception):
    def __init__(self, model_id: int) -> None:
        self.model_id = model_id
        super().__init__(f"Embedding model {model_id} not found")


class EmbeddingJobNotFoundError(Exception):
    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"Embedding job {job_id} not found")


class MigrationTargetNotFoundError(Exception):
    def __init__(self, version_id: int) -> None:
        self.version_id = version_id
        super().__init__(f"Document version {version_id} not found")


def embed_version(db, version_id: int) -> None:
    """버전의 document_chunks 전체를 활성 모델로 임베딩한다. 파싱→청킹 파이프라인의 마지막 단계."""
    version = db.get(DocumentVersion, version_id)
    if version is None:
        return

    version.processing_status = "EMBEDDING"
    db.commit()

    try:
        settings = get_settings()
        active_model = EmbeddingModelRepository(db).get_active()
        if active_model is None:
            version.processing_status = "CHUNKED"
            db.commit()
            logger.info("embed_version %s: no active embedding model, staying CHUNKED", version_id)
            return

        chunks = DocumentVersionRepository(db).list_chunks(version_id)
        if not chunks:
            version.processing_status = "READY"
            db.commit()
            return

        provider = get_embedding_provider(settings, active_model)
        embeddings_repo = ChunkEmbeddingRepository(db)
        already = embeddings_repo.existing_chunk_ids([c.id for c in chunks], active_model.id)
        pending = [c for c in chunks if c.id not in already]

        rows: list[ChunkEmbedding] = []
        batch_size = settings.embedding_batch_size
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            vectors = provider.embed_documents([c.content for c in batch])
            rows.extend(
                ChunkEmbedding(
                    chunk_id=chunk.id, embedding_model_id=active_model.id, embedding=vector
                )
                for chunk, vector in zip(batch, vectors)
            )
        embeddings_repo.bulk_add(rows)

        version.processing_status = "READY"
        db.commit()
        logger.info(
            "embedded version %s: %s new vectors (model=%s)",
            version_id, len(rows), active_model.model_key,
        )
    except Exception as exc:
        db.rollback()
        version = db.get(DocumentVersion, version_id)
        if version is not None:
            version.processing_status = "CHUNKED"
            db.commit()
        logger.exception("embedding failed for version %s, reverted to CHUNKED: %s", version_id, exc)


def run_reembed_task(job_id: int, model_id: int) -> None:
    """BackgroundTasks 진입점 — 지정 모델로 전체 document_chunks를 재임베딩"""
    db = SessionLocal()
    try:
        settings = get_settings()
        jobs = EmbeddingJobRepository(db)
        models = EmbeddingModelRepository(db)
        embeddings = ChunkEmbeddingRepository(db)

        job = jobs.get(job_id)
        model = models.get(model_id)
        if job is None or model is None:
            logger.warning("run_reembed_task: job %s or model %s not found", job_id, model_id)
            return

        try:
            provider = get_embedding_provider(settings, model)
            chunk_ids = list(db.scalars(select(DocumentChunk.id)))
            already = embeddings.existing_chunk_ids(chunk_ids, model.id)
            pending_ids = [cid for cid in chunk_ids if cid not in already]
            pending_chunks = list(
                db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(pending_ids)))
            ) if pending_ids else []

            batch_size = settings.embedding_batch_size
            for i in range(0, len(pending_chunks), batch_size):
                batch = pending_chunks[i : i + batch_size]
                vectors = provider.embed_documents([c.content for c in batch])
                rows = [
                    ChunkEmbedding(chunk_id=c.id, embedding_model_id=model.id, embedding=v)
                    for c, v in zip(batch, vectors)
                ]
                embeddings.bulk_add(rows)
                job.processed_count += len(batch)
                db.commit()

            job.status = "COMPLETED"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("reembed job %s completed: %s chunks (model=%s)",
                        job_id, len(pending_chunks), model.model_key)
        except Exception as exc:
            db.rollback()
            job = jobs.get(job_id)
            if job is not None:
                job.status = "FAILED"
                job.error = str(exc)[:2000]
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
            logger.exception("reembed job %s failed: %s", job_id, exc)
    finally:
        db.close()


class EmbeddingService:
    def __init__(
        self,
        models: EmbeddingModelRepository,
        chunk_embeddings: ChunkEmbeddingRepository,
        jobs: EmbeddingJobRepository,
        settings: Settings,
    ) -> None:
        self.models = models
        self.chunk_embeddings = chunk_embeddings
        self.jobs = jobs
        self.settings = settings

    def list_models(self) -> list[EmbeddingModel]:
        return self.models.list()

    def get_model(self, model_id: int) -> EmbeddingModel:
        model = self.models.get(model_id)
        if model is None:
            raise EmbeddingModelNotFoundError(model_id)
        return model

    def activate_model(self, model_id: int) -> EmbeddingModel:
        model = self.get_model(model_id)
        return self.models.activate(model)

    def start_reembed(self, model_id: int) -> EmbeddingJob:
        """청킹은 그대로 두고 이 모델로 전체 재임베딩할 job을 만든다"""
        self.get_model(model_id)  # 존재 확인
        target = self.chunk_embeddings.count_all_chunks()
        job = EmbeddingJob(
            job_type="reembed", embedding_model_id=model_id, status="RUNNING", target_count=target
        )
        return self.jobs.add(job)

    def get_job(self, job_id: int) -> EmbeddingJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise EmbeddingJobNotFoundError(job_id)
        return job

    def start_migration(self, versions: DocumentVersionRepository, version_ids: list[int]) -> EmbeddingJob:
        """관리자가 EmbeddingLab에서 고른 기존 문서를 재청킹+임베딩할 job을 만든다"""
        for version_id in version_ids:
            if versions.get(version_id) is None:
                raise MigrationTargetNotFoundError(version_id)
        job = EmbeddingJob(job_type="migrate", status="RUNNING", target_count=len(version_ids))
        return self.jobs.add(job)


def get_embedding_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EmbeddingService:
    return EmbeddingService(
        EmbeddingModelRepository(db),
        ChunkEmbeddingRepository(db),
        EmbeddingJobRepository(db),
        settings,
    )
