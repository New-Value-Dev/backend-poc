"""기존 비정형 문서 마이그레이션 — 관리자가 EmbeddingLab에서 고른 document_version을
재청킹(semantic 강제 가능)+임베딩한다.

document_chunks/chunk_embeddings는 chunk_version()이 delete+insert로 덮어쓴다
(ChunkEmbedding은 ondelete=CASCADE라 자동 정리). 새 document_version은 만들지 않는다 —
원본 파일이 안 바뀌었으므로 버전 증가는 의미상 부적절하다(correction-apply의 버전 증가와는
다른 케이스).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.repositories.chunking_config_repository import ChunkingConfigRepository
from app.repositories.embedding_repository import EmbeddingJobRepository
from app.services.chunking.base import ChunkingParams
from app.services.chunking_service import chunk_version
from app.services.embedding_service import embed_version

logger = logging.getLogger(__name__)


def _force_semantic_params(db) -> ChunkingParams:
    """강제 semantic용 파라미터 — 크기/윈도우는 활성 설정을 따르되 strategy만 override한다."""
    active = ChunkingConfigRepository(db).get_active()
    if active is not None:
        return ChunkingParams(
            strategy="semantic",
            max_chars=active.chunk_max_chars,
            min_chars=active.chunk_min_chars,
            overlap=active.chunk_overlap_chars,
            sentence_window=active.sentence_window,
            breakpoint_percentile=active.breakpoint_percentile,
        )
    settings = get_settings()
    return ChunkingParams(
        strategy="semantic",
        max_chars=settings.chunk_max_chars,
        min_chars=settings.chunk_min_chars,
        overlap=settings.chunk_overlap_chars,
        sentence_window=settings.chunk_semantic_sentence_window,
        breakpoint_percentile=settings.chunk_semantic_breakpoint_percentile,
    )


def run_migration_task(job_id: int, version_ids: list[int], force_semantic: bool = False) -> None:
    """BackgroundTasks 진입점 — 자체 세션으로 순차 재청킹+임베딩하고 job 진행률을 갱신한다."""
    db = SessionLocal()
    try:
        jobs = EmbeddingJobRepository(db)
        job = jobs.get(job_id)
        if job is None:
            logger.warning("run_migration_task: job %s not found", job_id)
            return

        # force_semantic=False면 config=None으로 넘겨 chunk_version이 활성 설정/heading 자동
        # 판정을 그대로 쓰게 한다 — "이 문서들은 비정형이라 semantic으로 강제" 의도만 override.
        config = _force_semantic_params(db) if force_semantic else None

        try:
            for version_id in version_ids:
                chunk_version(db, version_id, config=config)
                embed_version(db, version_id)
                job.processed_count += 1
                db.commit()

            job.status = "COMPLETED"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("migration job %s completed: %s versions", job_id, len(version_ids))
        except Exception as exc:
            db.rollback()
            job = jobs.get(job_id)
            if job is not None:
                job.status = "FAILED"
                job.error = str(exc)[:2000]
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
            logger.exception("migration job %s failed: %s", job_id, exc)
    finally:
        db.close()
