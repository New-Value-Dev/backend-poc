from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.rag import RagAnswerRead, RagHistoryItem, RagQueryRequest
from app.services.llm import LLMError
from app.services.rag_service import (
    EmbeddingModelNotConfiguredError,
    RagService,
    get_rag_service,
)

router = APIRouter(tags=["rag"])

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}


@router.post(
    "/rag/query",
    response_model=RagAnswerRead,
    summary="질문에 대해 문서 기반 답변 생성",
    responses={
        **AUTH_RESPONSES,
        409: {"description": "활성 임베딩 모델이 아직 없음(임베딩된 문서가 없음)"},
        502: {"description": "LLM provider 호출 실패(네트워크/키/과금 등)"},
    },
)
def query(
    body: RagQueryRequest,
    service: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
) -> RagAnswerRead:
    try:
        return service.ask(
            body.question,
            project_ids=body.scope.project_ids if body.scope else None,
            folder_ids=body.scope.folder_ids if body.scope else None,
            created_by=str(current_user.id),
        )
    except EmbeddingModelNotConfiguredError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "임베딩된 문서가 아직 없습니다"
        ) from None
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None


@router.get(
    "/rag/history",
    response_model=list[RagHistoryItem],
    summary="최근 질의 이력",
    responses={**AUTH_RESPONSES},
)
def history(
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    service: RagService = Depends(get_rag_service),
    _: User = Depends(get_current_user),
) -> list[RagHistoryItem]:
    return service.history(limit=limit)
