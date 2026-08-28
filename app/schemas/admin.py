from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class UsageBucket(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    calls: int
    estimated_cost_usd: float


class UsageSummaryRead(BaseModel):
    """GET /admin/usage/summary — 토큰/비용 집계"""

    model: str
    period_start: datetime
    period_end: datetime
    source: str  # "actual" | "estimated"
    total: UsageBucket
    by_day: dict[str, UsageBucket]
    by_feature: dict[str, UsageBucket]
    status_counts: dict[str, int]
    avg_tokens_per_call: float
    avg_cost_per_call_usd: float


class LLMUsageLogRead(BaseModel):
    """성공/실패 로그 원본 1건"""

    model_config = {"from_attributes": True}

    id: int
    feature: str
    user_id: int | None
    project_id: int | None
    model: str
    status: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: float | None
    error_message: str | None
    created_at: datetime


class LLMUsageLogPage(BaseModel):
    items: list[LLMUsageLogRead]
    total: int
    page: int
    size: int


class BillingDailyRead(BaseModel):
    date: date
    amount_usd: float
    amount_krw: float | None = None


class BillingSummaryRead(BaseModel):
    """GET /admin/billing/summary — 실제 청구액(가능하면) + 로컬 추정치 + 환율"""

    actual_available: bool
    cost_source: str  # "actual" | "estimated"
    usd_krw_rate: float
    exchange_rate_as_of: datetime
    today_usd: float
    today_krw: float
    this_month_usd: float
    this_month_krw: float
    today_tokens: UsageBucket
    this_month_tokens: UsageBucket
    daily_actual: list[BillingDailyRead]


class KeywordRead(BaseModel):
    keyword: str
    count: int


class KeywordRankingRead(BaseModel):
    period_start: datetime
    period_end: datetime
    items: list[KeywordRead]


class RagAdminLogRead(BaseModel):
    message_id: int
    conversation_id: int
    user_id: int
    question: str | None
    answer: str
    citations: list[dict[str, Any]] | None
    provider: str | None
    retrieved_count: int | None
    latency_ms: float | None
    confidence: float | None
    created_at: datetime


class RagAdminLogPage(BaseModel):
    items: list[RagAdminLogRead]
    total: int
    page: int
    size: int
