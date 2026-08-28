"""모델별 토큰 단가(USD) — litellm이 공개 유지하는 가격표를 가져다 쓴다"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.model_price_cache import ModelPriceCache

logger = logging.getLogger(__name__)

CACHE_KEY = "litellm"


def _get_price_table(db: Session, settings: Settings) -> dict[str, Any]:
    cached = db.get(ModelPriceCache, CACHE_KEY)
    now = datetime.now(timezone.utc)
    ttl = timedelta(seconds=settings.price_table_cache_ttl_seconds)
    if cached and (now - cached.fetched_at) < ttl:
        return cached.data

    try:
        resp = httpx.get(settings.price_table_url, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("litellm 가격표 다운로드 실패")
        if cached:
            return cached.data
        return {}

    if cached:
        cached.data = data
        cached.fetched_at = now
    else:
        db.add(ModelPriceCache(id=CACHE_KEY, data=data, fetched_at=now))
    db.commit()
    return data


def estimate_cost_usd(
    db: Session,
    settings: Settings,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    """단가표에 없는 모델이면 None"""
    table = _get_price_table(db, settings)
    entry = table.get(model)
    if not entry:
        return None
    input_cost = entry.get("input_cost_per_token")
    output_cost = entry.get("output_cost_per_token")
    if input_cost is None or output_cost is None:
        return None
    return (prompt_tokens or 0) * input_cost + (completion_tokens or 0) * output_cost
