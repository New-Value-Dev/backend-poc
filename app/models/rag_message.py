from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.rag_conversation import RagConversation

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class RagMessage(CreatedAtMixin, Base):
    """대화 안의 한 턴. role=user는 질문, role=assistant는 GPT 답변 + 인용."""

    __tablename__ = "rag_messages"
    __table_args__ = (
        Index("ix_rag_messages_conversation_id", "conversation_id"),
        # 대시보드의 "오늘 RAG 질의 수"(ragToday)가 role+created_at 으로 센다.
        Index("ix_rag_messages_role_created_at", "role", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rag_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # assistant 턴에만: [{document_id, document_name, section_id, page_start, page_end,
    #                     score, chunk_id, heading_path}]
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # 답변을 만든 LLM provider 이름("openai:gpt-...", "mock")
    provider: Mapped[str | None] = mapped_column(String(100))
    # 검색된 청크 수 / 왕복 시간 — 품질 회귀를 나중에 되짚어볼 수 있게 남긴다.
    retrieved_count: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    # GPT 자기신고 confidence(0~1) — 검색 유사도와는 다른 축, provider가 값을 안 주거나 형식이 어긋나면 NULL
    confidence: Mapped[float | None] = mapped_column(Float)

    conversation: Mapped[RagConversation] = relationship(back_populates="messages")
