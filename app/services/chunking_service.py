"""청킹 파이프라인

파싱된 document_sections 를 RAG 검색 단위인 document_chunks 로 변환
단순 N자 절단이 아니라 조(제N조)/부칙 단위로 섹션을 재그룹핑한 뒤 그 안에서만
문장(및 항·호) 단위로 분할 -- PDF 파서가 헤딩을 못 잡거나 문장이 섹션 경계에서
쪼개진 문서에서도 조 하나가 최대한 한 청크(또는 같은 article_key를 공유하는
연속 청크)로 유지되도록 한다.
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

# 문장 경계(마침표류/줄바꿈) 뒤에서 자르되, 항(①~⑮)·호(1. 2. 3...) 마커 앞에서도
# 분리 우선 지점을 둔다 -- 조 단위로 병합된 그룹이 chunk_max_chars 를 넘어 다시
# 쪼개질 때 항/호 중간이 잘리지 않도록 하기 위함.
# 첫 번째 대안의 부정 lookbehind는 "1." 같은 호 번호 뒤의 마침표를 문장 종결로
# 오인해 번호와 본문("1." / "업무상...")을 갈라놓는 걸 막는다.
_SENTENCE_RE = re.compile(
    r"(?<=[.!?。」』\n])(?<!\d\.)(?<!\d\d\.)\s+"
    r"|(?=[①-⑮])"
    r"|(?=(?<!\S)\d{1,2}\.\s)"
)

# 조/장/절 시작 패턴 -- 새 섹션 그룹을 여는 유일한 신호. "제6조", "제6조의2",
# "제3장", "제6조(연차유급휴가)" 처럼 조 번호 뒤에 괄호 제목이 붙는 경우까지 포함.
_ARTICLE_RE = re.compile(
    r"^(제\s*\d{1,3}\s*(?:조|장|절)(?:\s*의\s*\d+)?(?:\s*[\(\[][^\)\]]{0,60}[\)\]])?)"
)
_ADDENDUM_RE = re.compile(r"^(부칙)")
# 항(①~⑮)·호(1.2.3...) 마커는 _ARTICLE_RE/_ADDENDUM_RE 에 안 걸리므로
# _build_section_groups 에서 자동으로 병합 대상이 된다(별도 정규식 불필요).
# 대신 같은 마커 패턴이 _SENTENCE_RE 에서는 분리 우선 지점으로 재사용된다.


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _hard_wrap(text: str, size: int) -> list[str]:
    """text 가 max_chars 를 넘는 단일 조각일 때의 최후 수단 절단.
    줄바꿈이 있으면(억지로 한 섹션에 붙은 표 등) 줄 단위로 먼저 채우고,
    그래도 한 줄이 size 를 넘으면 그 줄만 문자 단위로 자른다."""
    if "\n" not in text:
        return [text[i : i + size] for i in range(0, len(text), size)]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(line) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend([line[i : i + size] for i in range(0, len(line), size)])
            continue
        if current and len(current) + 1 + len(line) > size:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


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


class _SectionGroup:
    """제N조/부칙 하나에 해당하는 연속 섹션 묶음. label 이 None 이면 첫 조가
    시작되기 전(또는 조 구조 자체가 없는 문서)에 나온 일반 섹션 묶음."""

    __slots__ = ("label", "sections")

    def __init__(self, label: str | None, section: DocumentSection) -> None:
        self.label = label
        self.sections: list[DocumentSection] = [section]


def _build_section_groups(sections: list[DocumentSection]) -> list[_SectionGroup]:
    """제N조/부칙 로 시작하는 섹션만 새 그룹을 열고, 그 외(항 ①②③, 호 1.2.3...,
    PDF 추출 과정에서 쪼개진 문장 조각 등)는 전부 직전 그룹에 이어붙인다.
    heading 타입 섹션은 그룹 경계에 관여하지 않는다(breadcrumb 용으로만 쓰임)."""
    groups: list[_SectionGroup] = []
    for section in sections:
        if section.section_type == "heading":
            continue
        content = (section.content or "").strip()
        if not content:
            continue
        match = _ARTICLE_RE.match(content) or _ADDENDUM_RE.match(content)
        if match is not None:
            groups.append(_SectionGroup(match.group(1).strip(), section))
        elif groups:
            groups[-1].sections.append(section)
        else:
            groups.append(_SectionGroup(None, section))
    return groups


def _build_chunks(version: DocumentVersion, sections: list[DocumentSection], settings):
    by_id = {s.id: s for s in sections}
    rows: list[DocumentChunk] = []
    index = 0
    for group in _build_section_groups(sections):
        anchor = group.sections[0]
        label = group.label

        base_path = _heading_path(anchor, by_id)
        path = [*base_path, label] if label else base_path

        # anchor.content 자체가 _ARTICLE_RE 매치를 만든 원본이라 label 은 이미
        # body 맨 앞에 자연히 포함돼 있다 -- 별도로 다시 붙이면 중복된다.
        full_text = "\n".join(
            stripped
            for s in group.sections
            if (stripped := (s.content or "").strip())
        )

        page_starts = [s.page_start for s in group.sections if s.page_start is not None]
        page_ends = [s.page_end for s in group.sections if s.page_end is not None]
        page_start = min(page_starts) if page_starts else None
        page_end = max(page_ends) if page_ends else None
        bbox = anchor.meta.get("bbox") if anchor.meta else None

        pieces = split_to_size(full_text, settings.chunk_max_chars, settings.chunk_overlap_chars)
        for i, piece in enumerate(pieces):
            if label and i > 0 and not piece.startswith(label):
                piece = f"[{label}] {piece}"
            meta: dict = {"heading_path": path, "section_type": anchor.section_type}
            if label:
                meta["article_key"] = label
            if bbox is not None:
                meta["bbox"] = bbox
            rows.append(
                DocumentChunk(
                    document_id=version.document_id,
                    document_version_id=version.id,
                    section_id=anchor.id,
                    chunk_index=index,
                    content=piece,
                    page_start=page_start,
                    page_end=page_end,
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
