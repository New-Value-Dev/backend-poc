"""청킹 파이프라인

파싱된 document_sections 를 RAG 검색 단위인 document_chunks 로 변환
heading이 있는 구조화 문서는 structure-aware 청킹
heading이 없는 자유 형식 문서는 semantic 청킹으로 자동 분기
processing_status: PARSED → CHUNKING → CHUNKED
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.models.document_chunk import DocumentChunk
from app.models.document_section import DocumentSection
from app.models.document_version import DocumentVersion
from app.repositories.chunking_config_repository import ChunkingConfigRepository
from app.repositories.embedding_repository import EmbeddingModelRepository
from app.services.chunking.base import ChunkDraft, ChunkingParams
from app.services.chunking.semantic_chunker import build_semantic_chunks
from app.services.chunking.structure_chunker import build_structure_chunks
from app.services.embedding.factory import get_embedding_provider

logger = logging.getLogger(__name__)


def _resolve_params(db, config: ChunkingParams | None) -> ChunkingParams:
    if config is not None:
        return config
    active = ChunkingConfigRepository(db).get_active()
    if active is not None:
        return ChunkingParams(
            strategy=active.strategy,
            max_chars=active.chunk_max_chars,
            min_chars=active.chunk_min_chars,
            overlap=active.chunk_overlap_chars,
            sentence_window=active.sentence_window,
            breakpoint_percentile=active.breakpoint_percentile,
        )
    settings = get_settings()
    return ChunkingParams(
        strategy="auto" if settings.chunk_strategy_auto else "structure",
        max_chars=settings.chunk_max_chars,
        min_chars=settings.chunk_min_chars,
        overlap=settings.chunk_overlap_chars,
        sentence_window=settings.chunk_semantic_sentence_window,
        breakpoint_percentile=settings.chunk_semantic_breakpoint_percentile,
    )


def _build_drafts(db, sections: list[DocumentSection], params: ChunkingParams) -> list[ChunkDraft]:
    has_headings = any(s.section_type == "heading" for s in sections)
    strategy = params.strategy
    if strategy == "auto":
        strategy = "semantic" if not has_headings else "structure"

    if strategy == "structure":
        return build_structure_chunks(
            sections,
            max_chars=params.max_chars,
            overlap=params.overlap,
            min_chars=params.min_chars,
        )

    # semantic 경로는 경계 탐지용 임베딩이 필요 
    settings = get_settings()
    active_model = EmbeddingModelRepository(db).get_active()
    if active_model is None:
        logger.warning("semantic chunking requested but no active embedding model — falling back to structure")
        return build_structure_chunks(
            sections,
            max_chars=params.max_chars,
            overlap=params.overlap,
            min_chars=params.min_chars,
        )

    provider = get_embedding_provider(settings, active_model)
    return build_semantic_chunks(
        sections,
        provider,
        max_chars=params.max_chars,
        overlap=params.overlap,
        sentence_window=params.sentence_window,
        breakpoint_percentile=params.breakpoint_percentile,
    )


def _to_document_chunk(
    draft: ChunkDraft, version: DocumentVersion, index: int
) -> DocumentChunk:
    return DocumentChunk(
        document_id=version.document_id,
        document_version_id=version.id,
        section_id=draft.section_id,
        chunk_index=index,
        content=draft.content,
        page_start=draft.page_start,
        page_end=draft.page_end,
        chunk_metadata=draft.chunk_metadata,
    )


def chunk_version(db, version_id: int, *, config: ChunkingParams | None = None) -> None:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        return

    version.processing_status = "CHUNKING"
    db.commit()

    try:
        params = _resolve_params(db, config)
        sections = list(
            db.scalars(
                select(DocumentSection)
                .where(DocumentSection.document_version_id == version_id)
                .order_by(DocumentSection.order_no)
            )
        )
        drafts = _build_drafts(db, sections, params)

        db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_version_id == version_id)
        )
        rows = [_to_document_chunk(d, version, i) for i, d in enumerate(drafts)]
        db.add_all(rows)
        version.processing_status = "CHUNKED"
        db.commit()
        logger.info("chunked version %s: %s chunks", version_id, len(rows))
    except Exception as exc:
        db.rollback()
        version = db.get(DocumentVersion, version_id)
        if version is not None:
            version.processing_status = "FAILED"
            db.commit()
        logger.exception("chunking failed for version %s: %s", version_id, exc)
