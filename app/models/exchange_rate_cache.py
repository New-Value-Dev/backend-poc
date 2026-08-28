from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExchangeRateCache(Base):
    """외부 환율 API 결과 캐시"""

    __tablename__ = "exchange_rate_cache"

    pair: Mapped[str] = mapped_column(String(20), primary_key=True)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
