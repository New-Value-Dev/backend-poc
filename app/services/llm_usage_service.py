from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.repositories.llm_usage_repository import LLMUsageRepository
from app.services.llm.base import LLMUsageEvent
from app.services.llm_pricing import estimate_cost_usd
from app.services.openai_costs_client import (
    OpenAICostsUnavailable,
    fetch_daily_costs_usd,
    fetch_daily_usage,
)

logger = logging.getLogger(__name__)

_EMPTY_BUCKET = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "calls": 0,
    "estimated_cost_usd": 0.0,
}


def usage_sink(
    db: Session, *, user_id: int | None, project_id: int | None
) -> Callable[[LLMUsageEvent], None]:
    """`get_llm_provider(settings, on_usage=usage_sink(db, ...))` 로 넘길 콜백 """

    def _sink(event: LLMUsageEvent) -> None:
        try:
            LLMUsageRepository(db).add(
                feature=event.feature,
                model=event.model,
                status=event.status,
                user_id=user_id,
                project_id=project_id,
                prompt_tokens=event.prompt_tokens,
                completion_tokens=event.completion_tokens,
                total_tokens=event.total_tokens,
                latency_ms=event.latency_ms,
                error_message=event.error_message,
            )
        except Exception:
            db.rollback()
            logger.exception("LLM usage log 기록 실패 (feature=%s)", event.feature)

    return _sink


def usage_summary(db: Session, start: datetime, end: datetime, settings: Settings | None = None) -> dict:
    """관리자 대시보드용 구간 토큰/추정비용/성공-실패 집계"""
    settings = settings or get_settings()
    repo = LLMUsageRepository(db)
    rows = repo.daily_totals(start, end)

    by_day: dict[str, dict] = defaultdict(
        lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0, "estimated_cost_usd": 0.0}
    )
    by_feature: dict[str, dict] = defaultdict(
        lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0, "estimated_cost_usd": 0.0}
    )
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0, "estimated_cost_usd": 0.0}
    model = settings.openai_model

    for day, feature, prompt_sum, completion_sum, total_sum, calls in rows:
        cost = estimate_cost_usd(db, settings, model, prompt_sum, completion_sum) or 0.0
        day_key = day.isoformat() if hasattr(day, "isoformat") else str(day)

        for bucket in (by_day[day_key], by_feature[feature], total):
            bucket["prompt_tokens"] += prompt_sum
            bucket["completion_tokens"] += completion_sum
            bucket["total_tokens"] += total_sum
            bucket["calls"] += calls
            bucket["estimated_cost_usd"] += cost

    status_rows = repo.status_counts(start, end)
    status_counts = {status: count for status, count in status_rows}

    avg_tokens_per_call = (
        total["total_tokens"] / total["calls"] if total["calls"] else 0.0
    )
    avg_cost_per_call_usd = (
        total["estimated_cost_usd"] / total["calls"] if total["calls"] else 0.0
    )

    return {
        "model": model,
        "total": total,
        "by_day": dict(by_day),
        "by_feature": dict(by_feature),
        "status_counts": status_counts,
        "avg_tokens_per_call": avg_tokens_per_call,
        "avg_cost_per_call_usd": avg_cost_per_call_usd,
    }


def usage_summary_from_api(settings: Settings, start: datetime, end: datetime) -> dict | None:
    """[start, end) 구간을 OpenAI Admin API 실제 값(Usage API의 토큰/호출 수 + Costs API의 실제 청구액)으로 집계"""
    end_exclusive = end.date() + timedelta(days=1)
    try:
        # 서로 독립적인 두 API 호출이라 병렬로 쏜다
        with ThreadPoolExecutor(max_workers=2) as pool:
            usage_future = pool.submit(fetch_daily_usage, settings, start=start.date(), end=end_exclusive)
            cost_future = pool.submit(fetch_daily_costs_usd, settings, start=start.date(), end=end_exclusive)
            usage_rows = usage_future.result()
            cost_rows = cost_future.result()
    except OpenAICostsUnavailable:
        return None

    cost_by_day: dict[date, float] = defaultdict(float)
    for c in cost_rows:
        cost_by_day[c.day] += c.amount_usd

    by_day: dict[str, dict] = defaultdict(lambda: dict(_EMPTY_BUCKET))
    for u in usage_rows:
        bucket = by_day[u.day.isoformat()]
        bucket["prompt_tokens"] += u.input_tokens
        bucket["completion_tokens"] += u.output_tokens
        bucket["total_tokens"] += u.input_tokens + u.output_tokens
        bucket["calls"] += u.calls

    total = dict(_EMPTY_BUCKET)
    for day_key, bucket in by_day.items():
        bucket["estimated_cost_usd"] = cost_by_day.get(date.fromisoformat(day_key), 0.0)
        total["prompt_tokens"] += bucket["prompt_tokens"]
        total["completion_tokens"] += bucket["completion_tokens"]
        total["total_tokens"] += bucket["total_tokens"]
        total["calls"] += bucket["calls"]
        total["estimated_cost_usd"] += bucket["estimated_cost_usd"]

    return {"total": total, "by_day": dict(by_day)}
