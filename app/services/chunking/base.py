"""청킹 공통 자료구조 + 크기 분할 안전장치
structure/semantic 두 전략이 모두 재사용하는 순수 로직(ORM 비의존)만 둔다
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

_SENTENCE_RE = re.compile(r"(?<=[.!?。」』\n])\s+")

ChunkingStrategy = Literal["auto", "structure", "semantic"]


@dataclass
class ChunkingParams:
    """청킹 오케스트레이션 파라미터"""

    strategy: ChunkingStrategy = "auto"
    max_chars: int = 1000
    # structure 청킹의 하한 — 이 길이에 닿을 때까지 같은 heading 아래 인접 본문 섹션을 뭉친다.
    # 0이면 뭉치지 않고 섹션 1개 = 청크 1개(구버전 동작).
    min_chars: int = 300
    overlap: int = 150
    sentence_window: int = 3
    breakpoint_percentile: float = 95.0


@dataclass
class ChunkDraft:
    """DocumentChunk 로 저장되기 전 중간 표현. structure/semantic 청커의 공통 반환 타입."""

    content: str
    page_start: int | None
    page_end: int | None
    section_id: int | None
    chunk_metadata: dict[str, Any] = field(default_factory=dict)


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
