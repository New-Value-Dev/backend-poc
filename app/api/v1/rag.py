import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.rag import (
    RagCitation,
    RagConversationDetail,
    RagConversationRead,
    RagHistoryItem,
    RagMessageRead,
    RagQueryRequest,
    RagQueryResponse,
    RagSearchHit,
    RagSearchRequest,
    RagSearchResponse,
)
from app.services.llm.base import LLMConfigError, LLMError
from app.services.project_service import ProjectForbiddenError, ProjectNotFoundError
from app.services.rag.retriever import NoActiveEmbeddingModelError
from app.services.rag_service import (
    RagConversationForbiddenError,
    RagConversationNotFoundError,
    RagService,
    get_rag_service,
)

router = APIRouter(prefix="/rag", tags=["rag"])

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
SCOPE_RESPONSES = {
    **AUTH_RESPONSES,
    403: {"description": "scope 에 지정한 프로젝트에 접근 권한이 없음"},
    404: {"description": "scope 에 지정한 프로젝트가 없음"},
    503: {"description": "활성 임베딩 모델이 없어 검색 불가"},
}


def _scope_guard(fn):

    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Project {exc.project_id} not found"
            ) from None
        except ProjectForbiddenError:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "이 프로젝트에 접근할 권한이 없습니다"
            ) from None
        except NoActiveEmbeddingModelError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None

    return run


@router.post(
    "/search",
    response_model=RagSearchResponse,
    summary="RAG 검색 (GPT 없이 근거 청크만)",
    response_description="유사도 상위 청크 목록 (자연어 답변 아님)",
    responses=SCOPE_RESPONSES,
)
def search(
    body: RagSearchRequest,
    service: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
) -> RagSearchResponse:
    """질문을 활성 임베딩 모델로 벡터화해 관련 청크를 찾는다"""
    result = _scope_guard(service.search)(
        body.question,
        current_user,
        scope=body.scope,
        top_k=body.top_k,
        min_score=body.min_score,
    )
    return RagSearchResponse(
        question=body.question,
        embedding_model=result.embedding_model_key,
        hits=[
            RagSearchHit(
                index=i,
                document_id=hit.document.id,
                document_name=hit.document.name,
                section_id=hit.chunk.section_id,
                chunk_id=hit.chunk.id,
                page_start=hit.chunk.page_start,
                page_end=hit.chunk.page_end,
                score=round(hit.score, 4),
                heading_path=hit.heading_path,
                content=hit.chunk.content,
                expanded=hit.expanded,
            )
            for i, hit in enumerate(result.chunks, start=1)
        ],
    )


@router.post(
    "/query",
    response_model=RagQueryResponse,
    summary="RAG 질의 (검색 + GPT 답변)",
    response_description="자연어 답변 + 인용(citations)",
    responses={
        **SCOPE_RESPONSES,
        502: {"description": "LLM 호출 실패"},
    },
)
def query(
    body: RagQueryRequest,
    service: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
) -> RagQueryResponse:
    """검색된 근거만 사용해 GPT가 답을 만든다.

    `conversation_id` 를 주면 그 대화에 이어 붙이고(이전 턴을 프롬프트에 포함), 생략하면
    새 대화를 만든다. 근거가 없으면 GPT는 "확인할 수 없습니다"로 답한다 — 없는 내용을
    만들지 않게 프롬프트에서 강제한다. 답변 본문의 `[1]` 표기는 `citations[].index` 와 대응한다.
    """
    try:
        conversation, message, citations, result, search_question = _scope_guard(service.query)(
            body.question,
            current_user,
            scope=body.scope,
            conversation_id=body.conversation_id,
            top_k=body.top_k,
        )
    except RagConversationNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Conversation {exc.conversation_id} not found"
        ) from None
    except RagConversationForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "다른 사용자의 대화입니다"
        ) from None
    except LLMConfigError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None

    return RagQueryResponse(
        conversation_id=conversation.id,
        message_id=message.id,
        question=body.question,
        search_question=search_question if search_question != body.question else None,
        answer=message.content,
        citations=[RagCitation(**c) for c in citations],
        provider=message.provider or "",
        embedding_model=result.embedding_model_key,
        retrieved_count=message.retrieved_count or 0,
        latency_ms=message.latency_ms or 0.0,
    )


@router.post(
    "/query/stream",
    summary="RAG 질의 스트리밍 (SSE)",
    response_description="text/event-stream — meta → delta* → citations → done (또는 error)",
    responses={
        **SCOPE_RESPONSES,
        503: {"description": "활성 임베딩 모델이 없거나 LLM 설정(API 키) 누락"},
    },
)
def query_stream(
    body: RagQueryRequest,
    service: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """`/rag/query` 와 같은 검색+답변이지만 답변을 토큰 단위로 흘려보낸다(Server-Sent Events).

    검색/권한 오류(404/403/503)는 스트림을 열기 전에 걸러 평범한 HTTP 에러로 응답하고,
    LLM 호출 자체의 실패(네트워크 오류 등)만 스트림 중 `error` 이벤트로 알린다 — 스트림이
    한 번 시작되면 HTTP 상태코드를 더 바꿀 수 없기 때문이다.

    각 이벤트는 `event: <type>\\ndata: <json>\\n\\n` 형식이다.
    - `meta`: `{conversation_id, embedding_model, retrieved_count, search_question}` (스트림 맨 처음).
      `search_question`은 후속 질문을 검색 전에 독립 질문으로 재작성한 결과 — 원래 질문과
      같으면(재작성 없었으면) 그냥 원문이 그대로 들어간다.
    - `delta`: `{text}` — 답변 조각. 이어 붙이면 최종 답변이 된다.
    - `citations`: `{citations}` — `[1]` 표기에서 뽑은 근거 목록(마지막 delta 다음, 한 번)
    - `done`: `{conversation_id, message_id, provider, retrieved_count, latency_ms}` (마지막)
    - `error`: `{detail}` — LLM 호출 실패 시(이 이벤트 후 스트림 종료, done 없음)
    """
    try:
        ctx = _scope_guard(service.query_stream_prepare)(
            body.question,
            current_user,
            scope=body.scope,
            conversation_id=body.conversation_id,
            top_k=body.top_k,
        )
    except RagConversationNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Conversation {exc.conversation_id} not found"
        ) from None
    except RagConversationForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "다른 사용자의 대화입니다"
        ) from None
    except LLMConfigError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None

    def event_source():
        for event, data in service.query_stream_events(ctx):
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/history",
    response_model=list[RagHistoryItem],
    summary="최근 RAG 질의",
    response_description="본인의 최근 질문 (대시보드/검색 화면 공용)",
    responses=AUTH_RESPONSES,
)
def history(
    limit: Annotated[int, Query(ge=1, le=100, description="최대 결과 수")] = 10,
    service: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
) -> list[RagHistoryItem]:
    """내가 최근에 물어본 질문 목록 (api-spec.md §2)"""
    return [
        RagHistoryItem(
            conversation_id=conversation.id,
            message_id=message.id,
            question=message.content,
            at=message.created_at,
        )
        for message, conversation in service.recent_questions(current_user, limit=limit)
    ]


@router.get(
    "/conversations",
    response_model=list[RagConversationRead],
    summary="내 대화 목록",
    response_description="최근 수정순 대화 목록",
    responses=AUTH_RESPONSES,
)
def list_conversations(
    limit: Annotated[int, Query(ge=1, le=100, description="최대 결과 수")] = 20,
    service: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
) -> list[RagConversationRead]:
    """챗 UI 사이드바용 대화 목록"""
    return [
        RagConversationRead.model_validate(c)
        for c in service.list_conversations(current_user, limit=limit)
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=RagConversationDetail,
    summary="대화 상세 (전체 메시지)",
    response_description="대화 메타 + 질문/답변 메시지 전체",
    responses={
        **AUTH_RESPONSES,
        403: {"description": "다른 사용자의 대화"},
        404: {"description": "대화 없음"},
    },
)
def get_conversation(
    conversation_id: int,
    service: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
) -> RagConversationDetail:
    """대화를 다시 열 때 쓴다. citations 는 assistant 메시지에만 담긴다."""
    try:
        conversation = service.get_conversation(conversation_id, current_user)
    except RagConversationNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Conversation {conversation_id} not found"
        ) from None
    except RagConversationForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "다른 사용자의 대화입니다"
        ) from None

    return RagConversationDetail(
        id=conversation.id,
        title=conversation.title,
        project_id=conversation.project_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            RagMessageRead(
                id=m.id,
                role=m.role,
                content=m.content,
                citations=[RagCitation(**c) for c in (m.citations or [])] or None,
                provider=m.provider,
                created_at=m.created_at,
            )
            for m in conversation.messages
        ],
    )
