"""RAG 검색(pgvector) + 대화 이력 DB 접근

검색 쿼리가 지켜야 하는 규칙 두 가지
1. `embedding_model_id = 활성 모델` — 문서와 질문은 반드시 같은 모델로 임베딩해야 한다
   모델별 벡터가 한 테이블에 공존하므로 필터가 없으면 차원은 같지만 의미 공간이 다른 벡터끼리 비교하게 된다
2. `document_versions.id = documents.current_version_id` — 교정 apply로 v2가 생기면 v1의 청크도 그대로 남아 있다 
    이 조건이 없으면 오탈자가 있던 구버전이 검색 결과에 섞인다
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import Select, and_, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models.chunk_embedding import ChunkEmbedding
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.rag_conversation import RagConversation
from app.models.rag_message import ROLE_ASSISTANT, ROLE_USER, RagMessage


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _prefix_tsquery_terms(text: str, *, min_len: int = 2, max_terms: int = 8) -> list[str]:
    """질문을 접두어 검색용 후보 토큰으로 쪼갠다.

    한 글자 토큰은 대부분 조사/어미 잔여물이라 뺀다(min_len). 
    토큰 수를 제한하는 건 tsquery 문자열이 지나치게 길어지는 걸 막기 위해서다.
    """
    seen: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if len(tok) < min_len or tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= max_terms:
            break
    return seen


class ChunkSearchRepository:
    """청크 벡터 검색"""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _scoped(
        stmt: Select,
        *,
        project_ids: list[int] | None,
        folder_ids: list[int] | None,
        accessible_project_ids=None,
    ) -> Select:
        if project_ids:
            stmt = stmt.where(Document.project_id.in_(project_ids))
        if folder_ids:
            stmt = stmt.where(Document.folder_id.in_(folder_ids))
        # 스코프를 지정하지 않았으면 "내가 접근 가능한 프로젝트 전체"로 좁힌다
        if accessible_project_ids is not None:
            stmt = stmt.where(Document.project_id.in_(accessible_project_ids))
        return stmt

    def search(
        self,
        query_vector: list[float],
        *,
        embedding_model_id: int,
        top_k: int,
        min_score: float = 0.0,
        project_ids: list[int] | None = None,
        folder_ids: list[int] | None = None,
        accessible_project_ids=None,
    ) -> list[tuple[DocumentChunk, Document, float]]:
        """코사인 유사도 상위 top_k 청크를 (chunk, document, score)로 돌려준다"""
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector)
        score = (1 - distance).label("score")

        stmt = (
            select(DocumentChunk, Document, score)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(
                DocumentVersion,
                and_(
                    DocumentVersion.id == Document.current_version_id,
                    DocumentVersion.id == DocumentChunk.document_version_id,
                ),
            )
            .where(ChunkEmbedding.embedding_model_id == embedding_model_id)
            .order_by(distance)
            .limit(top_k)
        )
        stmt = self._scoped(
            stmt,
            project_ids=project_ids,
            folder_ids=folder_ids,
            accessible_project_ids=accessible_project_ids,
        )
        rows = self.db.execute(stmt).all()
        return [(c, d, float(s)) for c, d, s in rows if float(s) >= min_score]

    def search_fts(
        self,
        query_text: str,
        *,
        top_k: int,
        project_ids: list[int] | None = None,
        folder_ids: list[int] | None = None,
        accessible_project_ids=None,
    ) -> list[tuple[DocumentChunk, Document, float]]:
        """전문(full-text) 검색 : 벡터 검색이 놓치는 고유명사/정확한 용어를 보완"""
        terms = _prefix_tsquery_terms(query_text)
        if not terms:
            return []
        tsquery = func.to_tsquery("simple", " | ".join(f"{t}:*" for t in terms))
        rank = func.ts_rank_cd(DocumentChunk.content_tsv, tsquery).label("rank")

        stmt = (
            select(DocumentChunk, Document, rank)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(
                DocumentVersion,
                and_(
                    DocumentVersion.id == Document.current_version_id,
                    DocumentVersion.id == DocumentChunk.document_version_id,
                ),
            )
            .where(DocumentChunk.content_tsv.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(top_k)
        )
        stmt = self._scoped(
            stmt,
            project_ids=project_ids,
            folder_ids=folder_ids,
            accessible_project_ids=accessible_project_ids,
        )
        rows = self.db.execute(stmt).all()
        return [(c, d, float(r)) for c, d, r in rows]

    def siblings_of(
        self, chunk: DocumentChunk, heading_path: list[str], *, limit: int
    ) -> list[DocumentChunk]:
        """같은 문서 / 같은 heading_path 아래의 다른 청크(조문 나머지 부분)를 순서대로 가져온다"""
        if not heading_path:
            return []
        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.document_version_id == chunk.document_version_id,
                DocumentChunk.id != chunk.id,
                DocumentChunk.chunk_metadata["heading_path"] == cast(heading_path, JSONB),
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
        )
        return list(self.db.scalars(stmt))


class RagConversationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, conversation: RagConversation) -> RagConversation:
        self.db.add(conversation)
        self.db.flush()
        return conversation

    def get(self, conversation_id: int) -> RagConversation | None:
        return self.db.get(RagConversation, conversation_id)

    def list_for_user(self, user_id: int, *, limit: int) -> list[RagConversation]:
        return list(
            self.db.scalars(
                select(RagConversation)
                .where(RagConversation.user_id == user_id)
                .order_by(RagConversation.updated_at.desc(), RagConversation.id.desc())
                .limit(limit)
            )
        )

    def delete(self, conversation: RagConversation) -> None:
        self.db.delete(conversation)


class RagMessageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, message: RagMessage) -> RagMessage:
        self.db.add(message)
        self.db.flush()
        return message

    def list_for_conversation(self, conversation_id: int) -> list[RagMessage]:
        return list(
            self.db.scalars(
                select(RagMessage)
                .where(RagMessage.conversation_id == conversation_id)
                .order_by(RagMessage.id)
            )
        )

    def recent_questions(
        self, *, limit: int, user_id: int | None = None
    ) -> list[tuple[RagMessage, RagConversation]]:
        """최근 질문 목록(GET /rag/history)"""
        stmt = (
            select(RagMessage, RagConversation)
            .join(RagConversation, RagConversation.id == RagMessage.conversation_id)
            .where(RagMessage.role == ROLE_USER)
            .order_by(RagMessage.created_at.desc(), RagMessage.id.desc())
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(RagConversation.user_id == user_id)
        return [(m, c) for m, c in self.db.execute(stmt).all()]

    def count_questions_since(
        self,
        since: datetime,
        *,
        project_id: int | None = None,
        accessible_project_ids=None,
    ) -> int:
        """대시보드 ragToday — 오늘 들어온 질문 수"""
        stmt = (
            select(func.count())
            .select_from(RagMessage)
            .join(RagConversation, RagConversation.id == RagMessage.conversation_id)
            .where(RagMessage.role == ROLE_USER, RagMessage.created_at >= since)
        )
        if project_id is not None:
            stmt = stmt.where(RagConversation.project_id == project_id)
        elif accessible_project_ids is not None:
            stmt = stmt.where(RagConversation.project_id.in_(accessible_project_ids))
        return self.db.scalar(stmt) or 0

    # ── 관리자 전용 (전체 사용자) ──

    def list_question_texts_between(self, start: datetime, end: datetime) -> list[str]:
        """검색 키워드 순위 집계용"""
        stmt = select(RagMessage.content).where(
            RagMessage.role == ROLE_USER,
            RagMessage.created_at >= start,
            RagMessage.created_at < end,
        )
        return list(self.db.scalars(stmt))

    def _preceding_question(self, conversation_id: int, before_id: int) -> str | None:
        stmt = (
            select(RagMessage.content)
            .where(
                RagMessage.conversation_id == conversation_id,
                RagMessage.role == ROLE_USER,
                RagMessage.id < before_id,
            )
            .order_by(RagMessage.id.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_admin_qa_page(
        self, *, limit: int, offset: int, user_id: int | None = None
    ) -> tuple[list[dict], int]:
        """관리자용 검색-답변 로그"""
        stmt = (
            select(RagMessage, RagConversation)
            .join(RagConversation, RagConversation.id == RagMessage.conversation_id)
            .where(RagMessage.role == ROLE_ASSISTANT)
        )
        count_stmt = (
            select(func.count())
            .select_from(RagMessage)
            .join(RagConversation, RagConversation.id == RagMessage.conversation_id)
            .where(RagMessage.role == ROLE_ASSISTANT)
        )
        if user_id is not None:
            stmt = stmt.where(RagConversation.user_id == user_id)
            count_stmt = count_stmt.where(RagConversation.user_id == user_id)
        stmt = (
            stmt.order_by(RagMessage.created_at.desc(), RagMessage.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = self.db.execute(stmt).all()
        total = self.db.scalar(count_stmt) or 0

        out = []
        for message, conversation in rows:
            out.append(
                {
                    "message_id": message.id,
                    "conversation_id": conversation.id,
                    "user_id": conversation.user_id,
                    "question": self._preceding_question(conversation.id, message.id),
                    "answer": message.content,
                    "citations": message.citations,
                    "provider": message.provider,
                    "retrieved_count": message.retrieved_count,
                    "latency_ms": message.latency_ms,
                    "confidence": message.confidence,
                    "created_at": message.created_at,
                }
            )
        return out, total
