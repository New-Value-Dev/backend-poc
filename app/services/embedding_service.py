"""임베딩 생성 파이프라인

document_chunks 를 임베딩 provider 에 태워 chunk_embeddings 에 저장한다.
processing_status: CHUNKED → EMBEDDING → READY
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.models.chunk_embedding import ChunkEmbedding
from app.models.document_version import DocumentVersion
from app.repositories.embedding_repository import (
    ChunkEmbeddingRepository,
    EmbeddingModelRepository,
)
from app.services.embedding import get_embedding_provider

logger = logging.getLogger(__name__)


def embed_version(db, version_id: int) -> None:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        return

    version.processing_status = "EMBEDDING"
    db.commit()

    settings = get_settings()
    try:
        provider = get_embedding_provider(settings)

        models = EmbeddingModelRepository(db)
        model = models.get_or_create_active(
            model_key=settings.embedding_model_key,
            model_name=settings.embedding_model_name,
            dimension=provider.dimension,
        )
        db.commit()  # get_or_create_active 는 flush만 했으므로 확정

        embeddings = ChunkEmbeddingRepository(db)
        chunks = embeddings.list_unembedded_chunks(version_id, model.id)
        if chunks:
            vectors = provider.embed_documents([c.content for c in chunks])
            rows = [
                ChunkEmbedding(chunk_id=c.id, embedding_model_id=model.id, embedding=v)
                for c, v in zip(chunks, vectors)
            ]
            embeddings.add_many(rows)

        version.processing_status = "READY"
        db.commit()
        logger.info("embedded version %s: %s chunks", version_id, len(chunks))
    except Exception as exc:
        db.rollback()
        version = db.get(DocumentVersion, version_id)
        if version is not None:
            version.processing_status = "FAILED"
            db.commit()
        logger.exception("embedding failed for version %s: %s", version_id, exc)
