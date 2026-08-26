"""의미 기반(semantic) 청킹

heading이 없는 자유 형식 문서(txt/hwpx, 스타일 없는 docx 등)를 위한 전략.
문장을 슬라이딩 윈도우로 묶어 임베딩하고, 인접 윈도우 간 코사인 거리가 튀는
지점(percentile breakpoint)을 경계로 잡는다 — LlamaIndex SemanticSplitterNodeParser 방식.
"""

from __future__ import annotations

import numpy as np

from app.models.document_section import DocumentSection
from app.services.chunking.base import ChunkDraft, _split_sentences, split_to_size
from app.services.embedding.base import EmbeddingProvider


def _flatten_sentences(
    sections: list[DocumentSection],
) -> tuple[list[str], list[DocumentSection]]:
    """body 섹션을 order대로 이어붙여 문장 목록 + 원 section 역매핑을 만든다."""
    sentences: list[str] = []
    owners: list[DocumentSection] = []
    for section in sections:
        if section.section_type == "heading":
            continue
        content = (section.content or "").strip()
        if not content:
            continue
        for sentence in _split_sentences(content):
            sentences.append(sentence)
            owners.append(section)
    return sentences, owners


def _find_boundaries(embeddings: np.ndarray, breakpoint_percentile: float) -> set[int]:
    """인접 윈도우 임베딩 간 코사인 거리 분포에서 상위 percentile을 넘는 지점을 경계로 삼는다

    embeddings는 이미 정규화되어 있어(provider.embed_documents) 내적 = 코사인 유사도
    """
    if len(embeddings) < 2:
        return set()
    sims = np.sum(embeddings[:-1] * embeddings[1:], axis=1)
    distances = 1.0 - sims
    threshold = np.percentile(distances, breakpoint_percentile)
    return {i for i, d in enumerate(distances) if d > threshold}


def _group_sentences(
    sentences: list[str], owners: list[DocumentSection], boundaries: set[int]
) -> list[tuple[str, list[DocumentSection]]]:
    """경계 인덱스(문장 i와 i+1 사이) 기준으로 문장을 병합한다."""
    groups: list[tuple[str, list[DocumentSection]]] = []
    buf_sentences: list[str] = []
    buf_owners: list[DocumentSection] = []
    for i, (sentence, owner) in enumerate(zip(sentences, owners)):
        buf_sentences.append(sentence)
        buf_owners.append(owner)
        if i in boundaries:
            groups.append((" ".join(buf_sentences), buf_owners))
            buf_sentences, buf_owners = [], []
    if buf_sentences:
        groups.append((" ".join(buf_sentences), buf_owners))
    return groups


def _draft_from_group(
    text: str,
    group_sections: list[DocumentSection],
    *,
    sentence_window: int,
    breakpoint_percentile: float,
) -> ChunkDraft:
    page_starts = [s.page_start for s in group_sections if s.page_start is not None]
    page_ends = [s.page_end for s in group_sections if s.page_end is not None]
    source_section_ids = sorted({s.id for s in group_sections})
    return ChunkDraft(
        content=text,
        page_start=min(page_starts) if page_starts else None,
        page_end=max(page_ends) if page_ends else None,
        section_id=group_sections[0].id,
        chunk_metadata={
            "chunking_strategy": "semantic",
            "sentence_window": sentence_window,
            "breakpoint_percentile": breakpoint_percentile,
            "heading_path": [],
            "source_section_ids": source_section_ids,
        },
    )


def build_semantic_chunks(
    sections: list[DocumentSection],
    provider: EmbeddingProvider,
    *,
    max_chars: int,
    overlap: int,
    sentence_window: int,
    breakpoint_percentile: float,
) -> list[ChunkDraft]:
    sentences, owners = _flatten_sentences(sections)
    if not sentences:
        return []

    window = max(1, sentence_window)
    window_texts = [
        " ".join(sentences[i : i + window]) for i in range(len(sentences))
    ]
    raw_vectors = provider.embed_documents(window_texts)
    embeddings = np.asarray(raw_vectors, dtype=np.float32)
    boundaries = _find_boundaries(embeddings, breakpoint_percentile)

    drafts: list[ChunkDraft] = []
    for text, group_sections in _group_sentences(sentences, owners, boundaries):
        draft = _draft_from_group(
            text,
            group_sections,
            sentence_window=window,
            breakpoint_percentile=breakpoint_percentile,
        )
        if len(draft.content) <= max_chars:
            drafts.append(draft)
            continue
        # 병합 결과가 상한을 넘으면 기존 안전장치(문장 경계 유지 + hard-wrap 폴백)를 그대로 적용
        for piece in split_to_size(draft.content, max_chars, overlap):
            drafts.append(
                ChunkDraft(
                    content=piece,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    section_id=draft.section_id,
                    chunk_metadata=dict(draft.chunk_metadata),
                )
            )
    return drafts
