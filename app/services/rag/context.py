"""근거 청크 → LLM 프롬프트 블록(RagContext) 변환"""

from __future__ import annotations

from app.services.llm.base import RagContext
from app.services.rag.retriever import RetrievedChunk


def build_contexts(hits: list[RetrievedChunk], max_chars: int) -> list[RagContext]:
    """넘겨받은 순서 그대로 번호를 1부터 매기고 본문을 max_chars 로 자른다"""
    contexts: list[RagContext] = []
    for i, hit in enumerate(hits, start=1):
        content = hit.chunk.content or ""
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars] + "…"
        contexts.append(RagContext(index=i, content=content, label=hit.label()))
    return contexts
