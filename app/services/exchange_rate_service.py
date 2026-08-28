from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.exchange_rate_cache import ExchangeRateCache

logger = logging.getLogger(__name__)

USD_KRW_PAIR = "USD_KRW"


def get_usd_krw_rate(db: Session, settings: Settings) -> tuple[float, datetime]:
    """(rate, as_of) 를 돌려준다"""
    cached = db.get(ExchangeRateCache, USD_KRW_PAIR)
    now = datetime.now(timezone.utc)
    ttl = timedelta(seconds=settings.exchange_rate_cache_ttl_seconds)
    if cached and (now - cached.fetched_at) < ttl:
        return cached.rate, cached.fetched_at

    try:
        resp = httpx.get(settings.exchange_rate_api_url, timeout=10.0)
        resp.raise_for_status()
        rate = float(resp.json()["rates"]["KRW"])
    except Exception:
        logger.exception("환율 API 호출 실패")
        if cached:
            return cached.rate, cached.fetched_at
        raise

    if cached:
        cached.rate = rate
        cached.fetched_at = now
    else:
        db.add(ExchangeRateCache(pair=USD_KRW_PAIR, rate=rate, fetched_at=now))
    db.commit()
    return rate, now
