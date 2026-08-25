from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RagScopeRequest(BaseModel):
    """검색 범위 — 비우면 전체 프로젝트/폴더 대상."""

    project_ids: list[int] | None = None
    folder_ids: list[int] | None = None


class RagQueryRequest(BaseModel):
    question: str
    scope: RagScopeRequest | None = None


class CitationRead(BaseModel):
    """답변이 실제로 근거로 삼은 chunk 1건."""

    model_config = ConfigDict(from_attributes=True)

    document_id: int
    document_name: str
    section_id: int | None
    chunk_id: int
    page_start: int | None
    page_end: int | None
    score: float


class RagAnswerRead(BaseModel):
    """RAG 질의 1건의 결과. rag_queries 1행에 대응."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    answer: str
    citations: list[CitationRead]
    provider: str | None
    created_at: datetime


class RagHistoryItem(BaseModel):
    """최근 질의 이력 목록 항목(답변 본문 제외)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    created_at: datetime
