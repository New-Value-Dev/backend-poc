"""RAG 질의응답 오케스트레이션

질문 임베딩 → 벡터 검색 → LLM 답변 생성(+인용) → 이력 저장 을 하나로 묶는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.rag_query import RagQuery
from app.repositories.embedding_repository import (
    ChunkEmbeddingRepository,
    EmbeddingModelRepository,
)
from app.repositories.rag_repository import RagQueryRepository
from app.schemas.rag import CitationRead, RagAnswerRead, RagHistoryItem
from app.services.activity_service import (
    Action,
    ActivityService,
    get_activity_service,
)
from app.services.embedding import EmbeddingProvider, get_embedding_provider
from app.services.llm import LLMProvider, RagContextChunk, get_llm_provider


class EmbeddingModelNotConfiguredError(Exception):
    """활성 임베딩 모델이 아직 없음(임베딩 파이프라인이 한 번도 안 돌았음)."""


def _section_title(chunk_metadata: dict | None) -> str | None:
    if not chunk_metadata:
        return None
    path = chunk_metadata.get("heading_path")
    return path[-1] if path else None


@dataclass
class _MatchedChunk:
    """검색된 chunk 1건 — search() Row 와 형제 확장으로 끌어온 Row 를 같은
    모양으로 다뤄서 contexts/citations 조립 코드가 출처를 신경 안 써도 되게 한다."""

    chunk_id: int
    content: str
    section_id: int | None
    document_version_id: int
    page_start: int | None
    page_end: int | None
    chunk_metadata: dict | None
    document_id: int
    document_name: str
    distance: float


def _to_matched_chunk(row, distance: float) -> _MatchedChunk:
    return _MatchedChunk(
        chunk_id=row.chunk_id,
        content=row.content,
        section_id=row.section_id,
        document_version_id=row.document_version_id,
        page_start=row.page_start,
        page_end=row.page_end,
        chunk_metadata=row.chunk_metadata,
        document_id=row.document_id,
        document_name=row.document_name,
        distance=distance,
    )


class RagService:
    def __init__(
        self,
        chunks: ChunkEmbeddingRepository,
        embedding_models: EmbeddingModelRepository,
        queries: RagQueryRepository,
        embedding_provider: EmbeddingProvider,
        llm: LLMProvider,
        settings: Settings,
        activity: ActivityService,
    ) -> None:
        self.chunks = chunks
        self.embedding_models = embedding_models
        self.queries = queries
        self.embedding_provider = embedding_provider
        self.llm = llm
        self.settings = settings
        self.activity = activity

    def ask(
        self,
        question: str,
        *,
        project_ids: list[int] | None,
        folder_ids: list[int] | None,
        created_by: str | None,
    ) -> RagAnswerRead:
        model = self.embedding_models.get_active()
        if model is None:
            raise EmbeddingModelNotConfiguredError()

        query_vector = self.embedding_provider.embed_query(question)
        rows = self.chunks.search(
            query_vector,
            model.id,
            top_k=self.settings.rag_top_k,
            project_ids=project_ids,
            folder_ids=folder_ids,
        )
        matched = [
            _to_matched_chunk(r, r.distance)
            for r in rows
            if (1 - r.distance) >= self.settings.rag_min_score
        ]
        rows = self._expand_siblings(matched) if self.settings.rag_expand_siblings else matched

        contexts = [
            RagContextChunk(
                index=i,
                document_name=r.document_name,
                section_title=_section_title(r.chunk_metadata),
                content=r.content[: self.settings.rag_context_max_chars],
            )
            for i, r in enumerate(rows)
        ]
        draft = self.llm.answer_with_citations(question, contexts)

        citations = [
            CitationRead(
                document_id=rows[i].document_id,
                document_name=rows[i].document_name,
                section_id=rows[i].section_id,
                chunk_id=rows[i].chunk_id,
                page_start=rows[i].page_start,
                page_end=rows[i].page_end,
                score=round(1 - rows[i].distance, 4),
            )
            for i in draft.used_indices
        ]

        record = self.queries.add(
            RagQuery(
                question=question,
                answer=draft.answer,
                project_ids=project_ids,
                folder_ids=folder_ids,
                citations=[c.model_dump() for c in citations],
                provider=self.llm.name,
                embedding_model_id=model.id,
                created_by=created_by,
            )
        )

        self.activity.record(
            Action.RAG_QUERY,
            target_type="rag_query",
            target_id=record.id,
            target_label=question[:200],
            meta={"citations": len(citations), "provider": self.llm.name},
        )

        return RagAnswerRead(
            id=record.id,
            question=question,
            answer=draft.answer,
            citations=citations,
            provider=self.llm.name,
            created_at=record.created_at,
        )

    def _expand_siblings(self, matched: list[_MatchedChunk]) -> list[_MatchedChunk]:
        """같은 article_key(조)를 공유하는 나머지 청크를 원래 매치 바로 뒤에 끼워
        넣는다. 조 하나가 chunk_max_chars 를 넘어 여러 청크로 쪼개졌을 때, 벡터
        검색에 그중 일부만 걸려도 나머지를 컨텍스트에 마저 채우기 위함.
        형제 청크는 독립적으로 채점된 게 아니라 원래 매치의 distance 를 물려받는다."""
        expanded: list[_MatchedChunk] = []
        seen_ids = {m.chunk_id for m in matched}
        extra_budget = self.settings.rag_expand_max_extra
        for match in matched:
            expanded.append(match)
            article_key = (match.chunk_metadata or {}).get("article_key")
            if not article_key or extra_budget <= 0:
                continue
            siblings = self.chunks.get_chunks_by_article_key(
                match.document_version_id, article_key, exclude_chunk_ids=seen_ids
            )
            for sibling in siblings:
                if extra_budget <= 0:
                    break
                if sibling.chunk_id in seen_ids:
                    continue
                expanded.append(_to_matched_chunk(sibling, match.distance))
                seen_ids.add(sibling.chunk_id)
                extra_budget -= 1
        return expanded

    def history(self, *, limit: int) -> list[RagHistoryItem]:
        return [
            RagHistoryItem.model_validate(row) for row in self.queries.list_recent(limit=limit)
        ]


def get_rag_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    activity: ActivityService = Depends(get_activity_service),
) -> RagService:
    return RagService(
        ChunkEmbeddingRepository(db),
        EmbeddingModelRepository(db),
        RagQueryRepository(db),
        get_embedding_provider(settings),
        get_llm_provider(settings),
        settings,
        activity,
    )
