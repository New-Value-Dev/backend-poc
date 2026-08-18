"""청킹 파이프라인

파싱된 document_sections 를 RAG 검색 단위인 document_chunks 로 변환
단순 N자 절단이 아니라 Section 경계를 보존하고 긴 섹션만 문장 단위로 분할
각 chunk 에는 상위 heading 경로를 meta 에 담아 검색 문맥을 보강
processing_status: PARSED → CHUNKING → CHUNKED
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.models.document_chunk import DocumentChunk
from app.models.document_section import DocumentSection
from app.models.document_version import DocumentVersion

logger = logging.getLogger(__name__)

_SENTENCE_RE = re.compile(r"(?<=[.!?。」』\n])\s+")


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _hard_wrap(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def split_to_size(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    current = ""
    for sentence in _split_sentences(text):
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_wrap(sentence, max_chars))
            continue
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (tail + " " + sentence).strip()
        else:
            current = (current + " " + sentence).strip() if current else sentence
    if current:
        chunks.append(current)
    return chunks


def _heading_path(section: DocumentSection, by_id: dict[int, DocumentSection]) -> list[str]:
    """부모 체인을 따라 올라가며 heading 제목 수집"""
    path: list[str] = []
    parent_id = section.parent_section_id
    while parent_id is not None:
        parent = by_id.get(parent_id)
        if parent is None:
            break
        if parent.section_type == "heading" and parent.title:
            path.append(parent.title)
        parent_id = parent.parent_section_id
    path.reverse()
    return path


def _build_chunks(version: DocumentVersion, sections: list[DocumentSection], settings):
    by_id = {s.id: s for s in sections}
    rows: list[DocumentChunk] = []
    index = 0
    for section in sections:
        if section.section_type == "heading":
            continue  # heading 자체는 chunk 로 만들지 않고 breadcrumb 로만 사용
        content = (section.content or "").strip()
        if not content:
            continue
        path = _heading_path(section, by_id)
        pieces = split_to_size(content, settings.chunk_max_chars, settings.chunk_overlap_chars)
        for piece in pieces:
            meta = {"heading_path": path, "section_type": section.section_type}
            if section.meta and "bbox" in section.meta:
                meta["bbox"] = section.meta["bbox"]
            rows.append(
                DocumentChunk(
                    document_id=version.document_id,
                    document_version_id=version.id,
                    section_id=section.id,
                    chunk_index=index,
                    content=piece,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    chunk_metadata=meta,
                )
            )
            index += 1
    return rows


def chunk_version(db, version_id: int) -> None:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        return

    version.processing_status = "CHUNKING"
    db.commit()

    settings = get_settings()
    try:
        sections = list(
            db.scalars(
                select(DocumentSection)
                .where(DocumentSection.document_version_id == version_id)
                .order_by(DocumentSection.order_no)
            )
        )
        db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_version_id == version_id)
        )
        rows = _build_chunks(version, sections, settings)
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
