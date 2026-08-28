from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ModelPriceCache(Base):
    """litellm이 공개 유지하는 모델별 단가표 캐시"""

    __tablename__ = "model_price_cache"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
