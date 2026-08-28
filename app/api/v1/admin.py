"""관리자 전용 AI 운영 대시보드"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.repositories.llm_usage_repository import LLMUsageRepository
from app.repositories.rag_repository import RagMessageRepository
from app.schemas.admin import (
    BillingDailyRead,
    BillingSummaryRead,
    KeywordRankingRead,
    KeywordRead,
    LLMUsageLogPage,
    LLMUsageLogRead,
    RagAdminLogPage,
    RagAdminLogRead,
    UsageBucket,
    UsageSummaryRead,
)
from app.services import exchange_rate_service, llm_usage_service, search_keyword_service

router = APIRouter(prefix="/admin", tags=["admin"])

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
ADMIN_RESPONSE = {403: {"description": "관리자 권한 필요"}}

Period = Literal["day", "month", "year"]


def _period_bounds(period: Period, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """period 라벨을 [start, end) UTC 구간으로 바꾼다. end는 항상 '지금'."""
    now = now or datetime.now(timezone.utc)
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _bucket(data: dict) -> UsageBucket:
    return UsageBucket(
        prompt_tokens=data["prompt_tokens"],
        completion_tokens=data["completion_tokens"],
        total_tokens=data["total_tokens"],
        calls=data["calls"],
        estimated_cost_usd=data["estimated_cost_usd"],
    )


_EMPTY_BUCKET_DICT = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "calls": 0,
    "estimated_cost_usd": 0.0,
}


def _sum_bucket_range(by_day: dict[str, dict], start: date, end: date) -> dict:
    """by_day 중 [start, end] 날짜만 합산 (fetch 구간이 통계 구간보다 넓을 때 사용)"""
    total = dict(_EMPTY_BUCKET_DICT)
    for day_key, bucket in by_day.items():
        if start <= date.fromisoformat(day_key) <= end:
            for k in _EMPTY_BUCKET_DICT:
                total[k] += bucket[k]
    return total


@router.get(
    "/usage/summary",
    response_model=UsageSummaryRead,
    summary="토큰 사용량/추정비용 집계 (일/월/년)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def usage_summary(
    period: Period = Query("month"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_admin),
) -> UsageSummaryRead:
    start, end = _period_bounds(period)
    local = llm_usage_service.usage_summary(db, start, end, settings)
    api_summary = llm_usage_service.usage_summary_from_api(settings, start, end)
    if api_summary is not None:
        source, total, by_day = "actual", api_summary["total"], api_summary["by_day"]
    else:
        source, total, by_day = "estimated", local["total"], local["by_day"]

    avg_tokens = total["total_tokens"] / total["calls"] if total["calls"] else 0.0
    avg_cost = total["estimated_cost_usd"] / total["calls"] if total["calls"] else 0.0

    return UsageSummaryRead(
        model=local["model"],
        period_start=start,
        period_end=end,
        source=source,
        total=_bucket(total),
        by_day={k: _bucket(v) for k, v in by_day.items()},
        by_feature={k: _bucket(v) for k, v in local["by_feature"].items()},
        status_counts=local["status_counts"],
        avg_tokens_per_call=avg_tokens,
        avg_cost_per_call_usd=avg_cost,
    )


@router.get(
    "/usage/logs",
    response_model=LLMUsageLogPage,
    summary="LLM 호출 성공/실패 로그 (페이지네이션)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def usage_logs(
    feature: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> LLMUsageLogPage:
    rows, total = LLMUsageRepository(db).list_page(
        feature=feature, status=status, limit=size, offset=(page - 1) * size
    )
    return LLMUsageLogPage(
        items=[LLMUsageLogRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/billing/summary",
    response_model=BillingSummaryRead,
    summary="AI API 사용 비용 요약 (KRW/USD) — 가능하면 OpenAI 실제 청구액, 아니면 로컬 추정치",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def billing_summary(
    chart_period: Period = Query("month", description="daily_actual(비용 추이 차트)이 커버할 기간"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_admin),
) -> BillingSummaryRead:
    rate, as_of = exchange_rate_service.get_usd_krw_rate(db, settings)

    today_start, now = _period_bounds("day")
    month_start, _ = _period_bounds("month")
    chart_start, _ = _period_bounds(chart_period)
    fetch_start = min(month_start, chart_start)
    today_key = today_start.date().isoformat()

    # 이번달 통계 + 차트 구간을 한 번의 API 왕복으로 같이 뽑는다
    api_summary = llm_usage_service.usage_summary_from_api(settings, fetch_start, now)
    if api_summary is not None:
        cost_source = "actual"
        month_bucket = _sum_bucket_range(api_summary["by_day"], month_start.date(), now.date())
        today_bucket = api_summary["by_day"].get(today_key, dict(_EMPTY_BUCKET_DICT))
        daily_actual = [
            BillingDailyRead(
                date=date.fromisoformat(day_key),
                amount_usd=bucket["estimated_cost_usd"],
                amount_krw=bucket["estimated_cost_usd"] * rate,
            )
            for day_key, bucket in sorted(api_summary["by_day"].items())
            if chart_start.date() <= date.fromisoformat(day_key) <= now.date()
        ]
    else:
        cost_source = "estimated"
        month_bucket = llm_usage_service.usage_summary(db, month_start, now, settings)["total"]
        today_bucket = llm_usage_service.usage_summary(db, today_start, now, settings)["total"]
        chart_local = llm_usage_service.usage_summary(db, chart_start, now, settings)
        daily_actual = [
            BillingDailyRead(
                date=date.fromisoformat(day_key),
                amount_usd=bucket["estimated_cost_usd"],
                amount_krw=bucket["estimated_cost_usd"] * rate,
            )
            for day_key, bucket in sorted(chart_local["by_day"].items())
        ]

    return BillingSummaryRead(
        actual_available=(cost_source == "actual"),
        cost_source=cost_source,
        usd_krw_rate=rate,
        exchange_rate_as_of=as_of,
        today_usd=today_bucket["estimated_cost_usd"],
        today_krw=today_bucket["estimated_cost_usd"] * rate,
        this_month_usd=month_bucket["estimated_cost_usd"],
        this_month_krw=month_bucket["estimated_cost_usd"] * rate,
        today_tokens=_bucket(today_bucket),
        this_month_tokens=_bucket(month_bucket),
        daily_actual=daily_actual,
    )


@router.get(
    "/search/keywords",
    response_model=KeywordRankingRead,
    summary="RAG 챗봇 질문 검색 키워드 순위 (형태소 분석 기반)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def search_keywords(
    period: Period = Query("month"),
    top: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> KeywordRankingRead:
    start, end = _period_bounds(period)
    ranked = search_keyword_service.top_keywords(db, start=start, end=end, limit=top)
    return KeywordRankingRead(
        period_start=start,
        period_end=end,
        items=[KeywordRead(keyword=k, count=c) for k, c in ranked],
    )


@router.get(
    "/rag/logs",
    response_model=RagAdminLogPage,
    summary="검색-답변 로그 (전체 사용자, 페이지네이션)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def rag_logs(
    user_id: int | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> RagAdminLogPage:
    rows, total = RagMessageRepository(db).list_admin_qa_page(
        limit=size, offset=(page - 1) * size, user_id=user_id
    )
    return RagAdminLogPage(
        items=[RagAdminLogRead(**row) for row in rows],
        total=total,
        page=page,
        size=size,
    )
