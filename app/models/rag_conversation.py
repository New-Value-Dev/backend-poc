from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.rag_message import RagMessage


class RagConversation(TimestampMixin, Base):
    """RAG 챗봇 대화 1건(스레드).

    질의를 단발로 저장하지 않고 대화로 묶는 이유: 후속 질문("그건 왜?")을 답하려면 이전
    턴을 프롬프트에 같이 넣어야 하고, 프론트가 챗 UI를 전제로 한다(api-spec.md §6).
    """

    __tablename__ = "rag_conversations"
    __table_args__ = (
        Index("ix_rag_conversations_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 검색 범위가 프로젝트 1개일 때만 채운다 — 대시보드/활동 로그의 project 스코프 집계용.
    # 여러 프로젝트를 걸친 대화는 NULL이고, 전체 범위는 아래 scope에 남는다.
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL")
    )
    # {"project_ids": [...], "folder_ids": [...]} — 대화 생성 시점의 검색 범위
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # 목록에 보여줄 제목. 첫 질문을 잘라서 넣는다.
    title: Mapped[str | None] = mapped_column(String(200))

    messages: Mapped[list[RagMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="RagMessage.id",
    )
