"""RAG 검색 단계(Retrieval) — GPT 이전 단계"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import Settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.repositories.embedding_repository import EmbeddingModelRepository
from app.repositories.rag_repository import ChunkSearchRepository
from app.services.embedding.factory import get_embedding_provider

logger = logging.getLogger(__name__)


class NoActiveEmbeddingModelError(Exception):
    """활성 임베딩 모델이 없으면 질문을 문서와 같은 공간으로 임베딩할 수 없다"""


@dataclass
class RetrievedChunk:
    """검색된 근거 1개."""

    chunk: DocumentChunk
    document: Document
    score: float
    # 검색으로 직접 걸린 게 아니라 같은 heading 아래에서 문맥 보강용으로 끌어온 청크
    # 인용(citation)은 직접 걸린 청크만 쓴다.
    expanded: bool = False

    @property
    def heading_path(self) -> list[str]:
        meta = self.chunk.chunk_metadata or {}
        path = meta.get("heading_path") or []
        return [str(p) for p in path] if isinstance(path, list) else []

    def label(self) -> str:
        """프롬프트/인용에 노출할 출처 라벨."""
        parts = [self.document.name]
        parts.extend(self.heading_path)
        label = " > ".join(p for p in parts if p)
        if self.chunk.page_start:
            label += f" (p.{self.chunk.page_start})"
        return label


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    embedding_model_id: int | None = None
    embedding_model_key: str | None = None

    @property
    def primary(self) -> list[RetrievedChunk]:
        return [c for c in self.chunks if not c.expanded]


class Retriever:
    def __init__(
        self,
        search: ChunkSearchRepository,
        models: EmbeddingModelRepository,
        settings: Settings,
    ) -> None:
        self.search = search
        self.models = models
        self.settings = settings

    def retrieve(
        self,
        question: str,
        *,
        project_ids: list[int] | None = None,
        folder_ids: list[int] | None = None,
        accessible_project_ids=None,
        top_k: int | None = None,
        min_score: float | None = None,
        expand_siblings: bool | None = None,
    ) -> RetrievalResult:
        active = self.models.get_active()
        if active is None:
            raise NoActiveEmbeddingModelError(
                "활성 임베딩 모델이 없어 검색할 수 없습니다"
            )

        final_k = top_k or self.settings.rag_top_k
        provider = get_embedding_provider(self.settings, active)
        query_vector = provider.embed_query(question)

        vector_hits = self.search.search(
            query_vector,
            embedding_model_id=active.id,
            top_k=self._candidate_k(final_k),
            min_score=self.settings.rag_min_score if min_score is None else min_score,
            project_ids=project_ids,
            folder_ids=folder_ids,
            accessible_project_ids=accessible_project_ids,
        )

        if self.settings.rag_hybrid_enabled:
            fts_hits = self.search.search_fts(
                question,
                top_k=self._candidate_k(final_k),
                project_ids=project_ids,
                folder_ids=folder_ids,
                accessible_project_ids=accessible_project_ids,
            )
            found = self._rrf_fuse(vector_hits, fts_hits, final_k)
        else:
            found = [
                RetrievedChunk(chunk=c, document=d, score=s)
                for c, d, s in vector_hits[:final_k]
            ]

        result = RetrievalResult(
            chunks=found,
            embedding_model_id=active.id,
            embedding_model_key=active.model_key,
        )
        should_expand = (
            self.settings.rag_expand_siblings if expand_siblings is None else expand_siblings
        )
        if should_expand and found:
            result.chunks = found + self._expand(found)
        return result

    def _candidate_k(self, final_k: int) -> int:
        """융합 전 후보 풀 크기. 최종 개수보다 넉넉해야 RRF가 순위를 재배열할 여지가 있다."""
        return max(final_k, self.settings.rag_hybrid_candidate_k)

    def _rrf_fuse(
        self,
        vector_hits: list[tuple[DocumentChunk, Document, float]],
        fts_hits: list[tuple[DocumentChunk, Document, float]],
        final_k: int,
    ) -> list[RetrievedChunk]:
        """두 후보 목록을 순위만으로 하나로 => Reciprocal Rank Fusion 알고리즘"""
        k = self.settings.rag_hybrid_rrf_k
        fused: dict[int, float] = {}
        payload: dict[int, tuple[DocumentChunk, Document]] = {}
        for rank, (chunk, doc, _score) in enumerate(vector_hits, start=1):
            fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (k + rank)
            payload.setdefault(chunk.id, (chunk, doc))
        for rank, (chunk, doc, _score) in enumerate(fts_hits, start=1):
            fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (k + rank)
            payload.setdefault(chunk.id, (chunk, doc))

        ordered_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:final_k]
        return [
            RetrievedChunk(chunk=payload[cid][0], document=payload[cid][1], score=fused[cid])
            for cid in ordered_ids
        ]

    def _expand(self, hits: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """검색된 청크와 같은 조/절(heading_path)의 나머지를 문맥으로 덧붙인다."""
        budget = self.settings.rag_expand_max_extra
        if budget <= 0:
            return []

        seen = {h.chunk.id for h in hits}
        extras: list[RetrievedChunk] = []
        for hit in hits:
            if budget <= 0:
                break
            for sibling in self.search.siblings_of(
                hit.chunk, hit.heading_path, limit=budget
            ):
                if sibling.id in seen:
                    continue
                seen.add(sibling.id)
                extras.append(
                    RetrievedChunk(
                        chunk=sibling,
                        document=hit.document,
                        score=hit.score,  # 직접 검색된 게 아니므로 부모의 점수를 물려준다
                        expanded=True,
                    )
                )
                budget -= 1
                if budget <= 0:
                    break
        return extras
