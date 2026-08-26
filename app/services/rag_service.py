"""RAG 챗봇 서비스 : 검색 + 생성을 잇는 계층
질문 → Retriever(로컬 임베딩 + pgvector) → 근거 청크 → LLMProvider(GPT) → 답변 + 인용

두 단계를 굳이 나눠 둔 이유: 답변이 이상할 때 "검색이 엉뚱한 걸 가져왔나"와 "GPT가 제대로
가져온 걸 잘못 읽었나"를 가릴 수 있어야 한다. `search()`는 ①만, `query()`는 ①+②다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.rag_conversation import RagConversation
from app.models.rag_message import ROLE_ASSISTANT, ROLE_USER, RagMessage
from app.models.user import User
from app.repositories.embedding_repository import EmbeddingModelRepository
from app.repositories.rag_repository import (
    ChunkSearchRepository,
    RagConversationRepository,
    RagMessageRepository,
)
from app.schemas.rag import RagScope, RagStreamErrorCode
from app.services.llm.base import (
    LLMError,
    LLMProvider,
    RagContext,
    extract_cited_indexes,
    strip_confidence_marker,
)
from app.services.llm.factory import get_llm_provider
from app.services.project_service import ProjectService, get_project_service
from app.services.rag.context import build_contexts
from app.services.rag.retriever import RetrievalResult, RetrievedChunk, Retriever

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 120

RAG_STREAM_FALLBACK_MESSAGES = {
    RagStreamErrorCode.LLM_CALL_FAILED: "답변을 가져오는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.",
    RagStreamErrorCode.EMPTY_ANSWER: "질문에 답할 근거를 찾지 못했습니다. 질문을 조금 더 구체적으로 해보시겠어요?",
}

_CONFIDENCE_MARKER_SAFETY_WINDOW = 32


class RagConversationNotFoundError(Exception):
    def __init__(self, conversation_id: int) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"RAG conversation {conversation_id} not found")


class RagConversationForbiddenError(Exception):
    def __init__(self, conversation_id: int) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"RAG conversation {conversation_id} belongs to another user")


@dataclass
class RagStreamContext:
    """스트리밍 시작 전과 후를 잇는 상태"""

    question: str
    search_question: str
    user: User
    conversation: RagConversation | None
    project_ids: list[int]
    folder_ids: list[int]
    result: RetrievalResult
    contexts: list[RagContext]
    ordered: list[RetrievedChunk]
    provider: LLMProvider
    deltas: Iterable[str]


class RagService:
    def __init__(
        self,
        db: Session,
        retriever: Retriever,
        conversations: RagConversationRepository,
        messages: RagMessageRepository,
        projects: ProjectService,
        settings: Settings,
    ) -> None:
        self.db = db
        self.retriever = retriever
        self.conversations = conversations
        self.messages = messages
        self.projects = projects
        self.settings = settings

    # ── 공통 ──

    def _resolve_scope(self, scope: RagScope | None, user: User):
        """스코프에 적힌 프로젝트 접근 권한을 확인하고 (project_ids, folder_ids, 폴백필터)를 만든다"""
        project_ids = list(scope.project_ids) if scope else []
        folder_ids = list(scope.folder_ids) if scope else []
        for project_id in project_ids:
            self.projects.check_access(project_id, user)  # 권한 없으면 예외
        accessible = None if project_ids else self.projects.accessible_project_ids_for(user)
        return project_ids, folder_ids, accessible

    def _contexts(self, chunks: list[RetrievedChunk]) -> list[RagContext]:
        """근거 블록 조립"""
        primary = sorted(
            (c for c in chunks if not c.expanded), key=lambda c: c.score, reverse=True
        )
        expanded = sorted(
            (c for c in chunks if c.expanded),
            key=lambda c: (c.chunk.document_version_id, c.chunk.chunk_index),
        )
        # 절단/번호매기기는 퀴즈 생성과 공용
        return build_contexts(primary + expanded, self.settings.rag_context_max_chars)

    @staticmethod
    def _citation(index: int, hit: RetrievedChunk) -> dict:
        return {
            "index": index,
            "document_id": hit.document.id,
            "document_name": hit.document.name,
            "section_id": hit.chunk.section_id,
            "chunk_id": hit.chunk.id,
            "page_start": hit.chunk.page_start,
            "page_end": hit.chunk.page_end,
            "score": round(hit.score, 4),
            "heading_path": hit.heading_path,
        }

    # ── 검색만 (GPT 없음) ──

    def search(
        self,
        question: str,
        user: User,
        *,
        scope: RagScope | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
    ):
        project_ids, folder_ids, accessible = self._resolve_scope(scope, user)
        return self.retriever.retrieve(
            question,
            project_ids=project_ids or None,
            folder_ids=folder_ids or None,
            accessible_project_ids=accessible,
            top_k=top_k,
            min_score=min_score,
        )

    # ── 검색 + GPT 답변 ──

    def query(
        self,
        question: str,
        user: User,
        *,
        scope: RagScope | None = None,
        conversation_id: int | None = None,
        top_k: int | None = None,
    ) -> tuple[RagConversation, RagMessage, list[dict], object, str]:
        started = time.perf_counter()
        question = question.strip()

        conversation = (
            self._own_conversation(conversation_id, user)
            if conversation_id is not None
            else None
        )
        # 이어지는 대화면 스코프도 첫 질문의 것을 유지한다
        if conversation is not None and scope is None and conversation.scope:
            scope = RagScope(**conversation.scope)

        project_ids, folder_ids, accessible = self._resolve_scope(scope, user)
        history = self._history(conversation)
        provider = get_llm_provider(self.settings)
        # 검색에만 쓰는 재작성 
        search_question = self._rewrite_for_search(question, history, provider)

        result = self.retriever.retrieve(
            search_question,
            project_ids=project_ids or None,
            folder_ids=folder_ids or None,
            accessible_project_ids=accessible,
            top_k=top_k,
        )

        contexts = self._contexts(result.chunks)
        # contexts 와 같은 순서의 청크 목록 — 인용 번호를 청크로 되돌리는 데 쓴다
        ordered = sorted(
            (c for c in result.chunks if not c.expanded),
            key=lambda c: c.score,
            reverse=True,
        ) + sorted(
            (c for c in result.chunks if c.expanded),
            key=lambda c: (c.chunk.document_version_id, c.chunk.chunk_index),
        )

        answer = provider.answer_with_context(question, contexts, history)

        citations = [
            self._citation(idx, ordered[idx - 1])
            for idx in answer.cited_indexes
            if 1 <= idx <= len(ordered)
        ]
        latency_ms = (time.perf_counter() - started) * 1000

        if conversation is None:
            conversation = self.conversations.add(
                RagConversation(
                    user_id=user.id,
                    # 프로젝트가 정확히 하나일 때만 채운다(대시보드 project 스코프 집계용)
                    project_id=project_ids[0] if len(project_ids) == 1 else None,
                    scope={"project_ids": project_ids, "folder_ids": folder_ids},
                    title=question[:TITLE_MAX_CHARS],
                )
            )
        self.messages.add(
            RagMessage(conversation_id=conversation.id, role=ROLE_USER, content=question)
        )
        assistant = self.messages.add(
            RagMessage(
                conversation_id=conversation.id,
                role=ROLE_ASSISTANT,
                content=answer.answer,
                citations=citations,
                provider=provider.name,
                retrieved_count=len(result.chunks),
                latency_ms=round(latency_ms, 1),
                confidence=answer.confidence,
            )
        )
        self.db.commit()
        self.db.refresh(assistant)
        self.db.refresh(conversation)

        logger.info(
            "rag query: user=%s conv=%s retrieved=%s cited=%s provider=%s %.0fms",
            user.id, conversation.id, len(result.chunks), len(citations),
            provider.name, latency_ms,
        )
        return conversation, assistant, citations, result, search_question

    def _rewrite_for_search(
        self, question: str, history: list[tuple[str, str]], provider: LLMProvider
    ) -> str:
        """후속 질문을 검색용 독립 질문으로 바꾼다"""
        if not history or not self.settings.rag_query_rewrite_enabled:
            return question
        try:
            rewritten = provider.rewrite_query(question, history)
        except LLMError as exc:
            logger.warning("질문 재작성 실패, 원문으로 검색 진행: %s", exc)
            return question
        return rewritten.strip() or question

    # ── 검색 + GPT 답변 (SSE 스트리밍) ──
    def query_stream_prepare(
        self,
        question: str,
        user: User,
        *,
        scope: RagScope | None = None,
        conversation_id: int | None = None,
        top_k: int | None = None,
    ) -> RagStreamContext:
        """검색 + 대화 로딩 + LLM 스트림 생성기 준비. query()의 앞부분과 동일한 로직"""
        question = question.strip()

        conversation = (
            self._own_conversation(conversation_id, user)
            if conversation_id is not None
            else None
        )
        if conversation is not None and scope is None and conversation.scope:
            scope = RagScope(**conversation.scope)

        project_ids, folder_ids, accessible = self._resolve_scope(scope, user)
        history = self._history(conversation)
        provider = get_llm_provider(self.settings)
        search_question = self._rewrite_for_search(question, history, provider)

        result = self.retriever.retrieve(
            search_question,
            project_ids=project_ids or None,
            folder_ids=folder_ids or None,
            accessible_project_ids=accessible,
            top_k=top_k,
        )
        contexts = self._contexts(result.chunks)
        ordered = sorted(
            (c for c in result.chunks if not c.expanded),
            key=lambda c: c.score,
            reverse=True,
        ) + sorted(
            (c for c in result.chunks if c.expanded),
            key=lambda c: (c.chunk.document_version_id, c.chunk.chunk_index),
        )
        deltas = provider.answer_with_context_stream(question, contexts, history)

        return RagStreamContext(
            question=question,
            search_question=search_question,
            user=user,
            conversation=conversation,
            project_ids=project_ids,
            folder_ids=folder_ids,
            result=result,
            contexts=contexts,
            ordered=ordered,
            provider=provider,
            deltas=deltas,
        )

    def query_stream_events(self, ctx: RagStreamContext) -> Iterator[tuple[str, dict]]:
        """(event, data) 를 순서대로 낸다: meta → delta* → citations+done, 실패 시 error.

        LLM 호출 자체의 실패(네트워크 오류 등)는 스트림이 이미 열린 뒤에나 알 수 있어
        HTTP 상태코드를 못 바꾸므로 "error" 이벤트로 대신 알린다.
        """
        started = time.perf_counter()
        conversation = ctx.conversation
        is_new = conversation is None

        yield "meta", {
            "conversation_id": conversation.id if conversation else None,
            "embedding_model": ctx.result.embedding_model_key,
            "retrieved_count": len(ctx.result.chunks),
            # question 과 다르면 재작성이 적용된 것 — 원문과 같으면 재작성 없이 그대로 검색함.
            "search_question": ctx.search_question,
        }

        # [n] 인용 마커와 달리 confidence 마커([[CONF:0.xx]])는 사용자에게 보이면 안 되므로,
        # 스트림 끝부분(_CONFIDENCE_MARKER_SAFETY_WINDOW 만큼)은 즉시 내보내지 않고 버퍼에
        # 들고 있다가, 다음 델타가 오면 그만큼만 흘려보낸다. 스트림이 끝나면 남은 버퍼에서
        # 마커를 최종적으로 떼어낸다.
        chunks: list[str] = []
        pending = ""
        try:
            for delta in ctx.deltas:
                pending += delta
                overflow = len(pending) - _CONFIDENCE_MARKER_SAFETY_WINDOW
                if overflow > 0:
                    to_yield, pending = pending[:overflow], pending[overflow:]
                    chunks.append(to_yield)
                    yield "delta", {"text": to_yield}
        except LLMError:
            logger.exception(
                "rag stream: LLM 호출 실패 user=%s conv=%s",
                ctx.user.id, conversation.id if conversation else None,
            )
            code = RagStreamErrorCode.LLM_CALL_FAILED
            yield "error", {"code": code, "detail": RAG_STREAM_FALLBACK_MESSAGES[code]}
            return

        tail, confidence = strip_confidence_marker(pending)
        if tail:
            chunks.append(tail)
            yield "delta", {"text": tail}

        answer_text = "".join(chunks).strip()
        if not answer_text:
            code = RagStreamErrorCode.EMPTY_ANSWER
            yield "error", {"code": code, "detail": RAG_STREAM_FALLBACK_MESSAGES[code]}
            return

        valid = {c.index for c in ctx.contexts}
        cited_indexes = extract_cited_indexes(answer_text, valid)
        citations = [
            self._citation(idx, ctx.ordered[idx - 1])
            for idx in cited_indexes
            if 1 <= idx <= len(ctx.ordered)
        ]
        latency_ms = (time.perf_counter() - started) * 1000

        if is_new:
            conversation = self.conversations.add(
                RagConversation(
                    user_id=ctx.user.id,
                    project_id=ctx.project_ids[0] if len(ctx.project_ids) == 1 else None,
                    scope={"project_ids": ctx.project_ids, "folder_ids": ctx.folder_ids},
                    title=ctx.question[:TITLE_MAX_CHARS],
                )
            )
        self.messages.add(
            RagMessage(conversation_id=conversation.id, role=ROLE_USER, content=ctx.question)
        )
        assistant = self.messages.add(
            RagMessage(
                conversation_id=conversation.id,
                role=ROLE_ASSISTANT,
                content=answer_text,
                citations=citations,
                provider=ctx.provider.name,
                retrieved_count=len(ctx.result.chunks),
                latency_ms=round(latency_ms, 1),
                confidence=confidence,
            )
        )

        conversation_id = conversation.id
        message_id = assistant.id
        self.db.commit()

        logger.info(
            "rag query stream: user=%s conv=%s retrieved=%s cited=%s provider=%s %.0fms",
            ctx.user.id, conversation_id, len(ctx.result.chunks), len(citations),
            ctx.provider.name, latency_ms,
        )

        yield "citations", {"citations": citations}
        yield "done", {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "provider": ctx.provider.name,
            "retrieved_count": len(ctx.result.chunks),
            "latency_ms": round(latency_ms, 1),
            "confidence": confidence,
        }

    def _history(self, conversation: RagConversation | None) -> list[tuple[str, str]]:
        """(질문, 답변) 쌍을 오래된 순으로/ 마지막 rag_history_turns 턴만 넣는다"""
        if conversation is None or self.settings.rag_history_turns <= 0:
            return []
        rows = self.messages.list_for_conversation(conversation.id)
        turns: list[tuple[str, str]] = []
        pending: str | None = None
        for msg in rows:
            if msg.role == ROLE_USER:
                pending = msg.content
            elif pending is not None:
                turns.append((pending, msg.content))
                pending = None
        return turns[-self.settings.rag_history_turns :]

    # ── 대화 이력 ──

    def _own_conversation(self, conversation_id: int, user: User) -> RagConversation:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise RagConversationNotFoundError(conversation_id)
        if conversation.user_id != user.id:
            raise RagConversationForbiddenError(conversation_id)
        return conversation

    def list_conversations(self, user: User, *, limit: int = 20) -> list[RagConversation]:
        return self.conversations.list_for_user(user.id, limit=limit)

    def get_conversation(self, conversation_id: int, user: User) -> RagConversation:
        return self._own_conversation(conversation_id, user)

    def rename_conversation(self, conversation_id: int, user: User, title: str) -> RagConversation:
        conversation = self._own_conversation(conversation_id, user)
        conversation.title = title.strip()[:TITLE_MAX_CHARS]
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def delete_conversation(self, conversation_id: int, user: User) -> None:
        conversation = self._own_conversation(conversation_id, user)
        self.conversations.delete(conversation)
        self.db.commit()

    def recent_questions(self, user: User, *, limit: int = 10):
        """대시보드/검색 화면용 최근 질의 (본인 질의만)"""
        return self.messages.recent_questions(limit=limit, user_id=user.id)

    def count_today(self, *, project_id: int | None = None, accessible_project_ids=None) -> int:
        start = datetime.combine(
            datetime.now(timezone.utc).date(), dtime.min, tzinfo=timezone.utc
        )
        return self.messages.count_questions_since(
            start, project_id=project_id, accessible_project_ids=accessible_project_ids
        )


def get_rag_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    projects: ProjectService = Depends(get_project_service),
) -> RagService:
    return RagService(
        db,
        Retriever(ChunkSearchRepository(db), EmbeddingModelRepository(db), settings),
        RagConversationRepository(db),
        RagMessageRepository(db),
        projects,
        settings,
    )
