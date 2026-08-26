from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RagStreamErrorCode(str, Enum):
    """`/rag/query/stream` 의 error 이벤트 code"""

    LLM_CALL_FAILED = "llm_call_failed" # 스트림 도중 GPT 호출 자체가 실패(네트워크/API 오류)
    EMPTY_ANSWER = "empty_answer" # GPT가 빈 답변을 냄


class RagScope(BaseModel):
    """검색 범위. 생략하면 내가 접근 가능한 프로젝트 전체에서 찾는다"""

    project_ids: list[int] = Field(default_factory=list)
    folder_ids: list[int] = Field(default_factory=list)


class RagQueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    scope: RagScope | None = None
    # 이어서 묻는 경우 기존 대화 id 없으면 새 대화를 만든다
    conversation_id: int | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)


class RagSearchRequest(BaseModel):
    """GPT 없이 검색만 — 검색 품질 확인 / 의미 기반 문서검색용."""

    question: str = Field(min_length=2, max_length=2000)
    scope: RagScope | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)


class RagCitation(BaseModel):
    """답변이 근거로 쓴 청크. 프론트가 문서/페이지로 링크를 건다"""

    index: int  # 답변 본문의 [n] 표기와 대응
    document_id: int
    document_name: str
    section_id: int | None
    chunk_id: int
    page_start: int | None
    page_end: int | None
    # 하이브리드 검색(기본)에서는 벡터+FTS를 RRF로 합친 융합 점수
    score: float
    heading_path: list[str] = Field(default_factory=list)


class RagSearchHit(RagCitation):
    """검색 결과 1건 — citation 과 같은 필드 + 본문 미리보기"""

    content: str
    expanded: bool = False


class RagSearchResponse(BaseModel):
    question: str
    embedding_model: str | None
    hits: list[RagSearchHit]


class RagQueryResponse(BaseModel):
    conversation_id: int
    message_id: int
    question: str
    # 후속 질문이 검색 전에 독립 질문으로 재작성됐을 때만 채워진다
    search_question: str | None = None
    answer: str
    citations: list[RagCitation]
    provider: str
    embedding_model: str | None
    # 검색된 근거 수 -> 0이면 GPT가 "확인할 수 없습니다"로 답한다
    retrieved_count: int
    latency_ms: float
    # GPT 자기신고 confidence(0~1) — provider가 값을 안 주면 None
    confidence: float | None = None


class RagMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    citations: list[RagCitation] | None = None
    provider: str | None = None
    confidence: float | None = None
    created_at: datetime


class RagConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    project_id: int | None
    # 대화 생성 시점의 검색 범위 — 대화를 다시 열 때 프론트가 스코프 체크박스를 이 값으로 맞춘다
    scope: RagScope | None = None
    created_at: datetime
    updated_at: datetime


class RagConversationDetail(RagConversationRead):
    messages: list[RagMessageRead] = []


class RagConversationUpdate(BaseModel):
    """PATCH /rag/conversations/{id}"""

    # rag_service.TITLE_MAX_CHARS 와 맞춘 길이
    title: str = Field(min_length=1, max_length=120)


class RagHistoryItem(BaseModel):
    """GET /rag/history — 대시보드/검색 화면에 뿌리는 최근 질의"""

    conversation_id: int
    message_id: int
    question: str
    at: datetime
