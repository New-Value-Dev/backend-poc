"""구조 인식(structure-aware) 청킹.

heading이 있는 문서(회사 내규 등)를 위한 전략 — heading 섹션은 breadcrumb로만 쓰고, 본문
섹션은 같은 heading 아래에서 `min_chars`에 닿을 때까지 뭉쳐 하나의 청크로 만든다.
"""

from __future__ import annotations

from app.models.document_section import DocumentSection
from app.services.chunking.base import ChunkDraft, split_to_size


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


def _drafts_from_group(
    group: list[tuple[DocumentSection, str]],
    by_id: dict[int, DocumentSection],
    *,
    max_chars: int,
    overlap: int,
) -> list[ChunkDraft]:
    """뭉쳐진 본문 섹션 묶음을 청크로 만든다(상한 초과 시 기존 크기 분할 안전장치를 적용)."""
    sections = [s for s, _ in group]
    first = sections[0]
    content = "\n".join(text for _, text in group)
    page_starts = [s.page_start for s in sections if s.page_start is not None]
    page_ends = [s.page_end for s in sections if s.page_end is not None]

    meta: dict = {
        "chunking_strategy": "structure",
        "heading_path": _heading_path(first, by_id),
        "section_type": first.section_type,
    }
    if len(sections) > 1:
        # 어느 섹션들이 합쳐졌는지 남긴다(semantic 청커의 source_section_ids와 같은 규칙)
        meta["source_section_ids"] = [s.id for s in sections]
    elif first.meta and "bbox" in first.meta:
        # bbox는 섹션 1개일 때만 의미가 있다 — 여러 섹션을 합치면 한 좌표 영역을 가리키지 않는다
        meta["bbox"] = first.meta["bbox"]

    return [
        ChunkDraft(
            content=piece,
            page_start=min(page_starts) if page_starts else None,
            page_end=max(page_ends) if page_ends else None,
            section_id=first.id,
            chunk_metadata=dict(meta),
        )
        for piece in split_to_size(content, max_chars, overlap)
    ]


def build_structure_chunks(
    sections: list[DocumentSection],
    *,
    max_chars: int,
    overlap: int,
    min_chars: int = 0,
) -> list[ChunkDraft]:
    by_id = {s.id: s for s in sections}
    drafts: list[ChunkDraft] = []

    buffer: list[tuple[DocumentSection, str]] = []
    buffer_len = 0
    buffer_key: tuple[tuple[str, ...], str] | None = None

    def flush() -> None:
        nonlocal buffer, buffer_len, buffer_key
        if buffer:
            drafts.extend(
                _drafts_from_group(buffer, by_id, max_chars=max_chars, overlap=overlap)
            )
        buffer, buffer_len, buffer_key = [], 0, None

    for section in sections:
        if section.section_type == "heading":
            # heading 자체는 chunk로 만들지 않고 breadcrumb로만 쓴다. 다만 새 heading이 시작되면
            # 조항 경계를 넘어 뭉치지 않도록 여기서 끊는다(제목이 같은 형제 heading 대비)
            flush()
            continue
        content = (section.content or "").strip()
        if not content:
            continue

        # 서로 다른 heading 아래거나 종류가 다른 섹션은 섞지 않는다
        key = (tuple(_heading_path(section, by_id)), section.section_type)
        if buffer_key is not None and key != buffer_key:
            flush()

        buffer_key = key
        buffer.append((section, content))
        buffer_len += len(content)
        if buffer_len >= min_chars:
            flush()

    flush()
    return drafts
