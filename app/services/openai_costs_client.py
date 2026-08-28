"""OpenAI 조직 Admin API 클라이언트"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TypeVar

import httpx

from app.core.config import Settings

T = TypeVar("T")

_MAX_DAYS_PER_WINDOW = 31  # OpenAI가 bucket_width=1d에 강제하는 limit 상한과 동일


class OpenAICostsUnavailable(Exception):
    """Admin 키 미설정 또는 Admin API 호출 실패 — 로컬 추정치로 폴백해야 한다는 신호."""


@dataclass
class DailyCost:
    day: date
    amount_usd: float


@dataclass
class DailyUsage:
    day: date
    model: str
    calls: int
    input_tokens: int
    output_tokens: int


def _date_windows(start: date, end: date, *, max_days: int = _MAX_DAYS_PER_WINDOW) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cur = start
    while cur < end:
        window_end = min(cur + timedelta(days=max_days), end)
        windows.append((cur, window_end))
        cur = window_end
    return windows


def _fetch_window(
    settings: Settings,
    *,
    endpoint: str,
    window_start: date,
    window_end: date,
    extra_params: dict[str, object],
    parse_bucket: Callable[[dict, date], list[T]],
) -> list[T]:
    """창 하나(<= 31일)를 페이지네이션까지 포함해 끝까지 가져온다"""
    start_time = int(datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    end_time = int(datetime.combine(window_end, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    base = settings.openai_base_url.rstrip("/")

    out: list[T] = []
    page: str | None = None
    while True:
        params: dict[str, object] = {
            "start_time": start_time,
            "end_time": end_time,
            "bucket_width": "1d",
            "limit": _MAX_DAYS_PER_WINDOW,
            **extra_params,
        }
        if page:
            params["page"] = page
        resp = httpx.get(
            f"{base}/{endpoint}",
            headers={"Authorization": f"Bearer {settings.openai_admin_api_key}"},
            params=params,
            timeout=15.0,
        )
        resp.raise_for_status()
        body = resp.json()
        for bucket in body.get("data", []):
            bucket_day = datetime.fromtimestamp(bucket["start_time"], tz=timezone.utc).date()
            out.extend(parse_bucket(bucket, bucket_day))
        if not body.get("has_more"):
            break
        page = body.get("next_page")
        if not page:
            break
    return out


def _fetch_all_windows(
    settings: Settings,
    *,
    endpoint: str,
    start: date,
    end: date,
    extra_params: dict[str, object],
    parse_bucket: Callable[[dict, date], list[T]],
) -> list[T]:
    if not settings.openai_admin_api_key:
        raise OpenAICostsUnavailable("OPENAI_ADMIN_API_KEY 가 설정되지 않았습니다")

    windows = _date_windows(start, end)
    if not windows:
        return []
    try:
        results: list[T] = []
        with ThreadPoolExecutor(max_workers=min(8, len(windows))) as pool:
            futures = [
                pool.submit(
                    _fetch_window,
                    settings,
                    endpoint=endpoint,
                    window_start=w_start,
                    window_end=w_end,
                    extra_params=extra_params,
                    parse_bucket=parse_bucket,
                )
                for w_start, w_end in windows
            ]
            for future in futures:
                results.extend(future.result())
        return results
    except httpx.HTTPError as exc:
        raise OpenAICostsUnavailable(f"OpenAI Admin API 호출 실패({endpoint}): {exc}") from exc


def _key_filter(settings: Settings) -> dict[str, object]:
    """OPENAI_USAGE_API_KEY_ID가 설정돼 있으면 그 API 키의 사용량으로만 한정한다.

    조직에 다른 사이드 프로젝트가 같은 OpenAI 조직/프로젝트를 공유해 별도 API 키로
    호출하는 경우, 이 필터가 없으면 Admin API 집계에 다른 프로젝트 사용량이 섞인다.
    """
    if not settings.openai_usage_api_key_id:
        return {}
    return {"api_key_ids": [settings.openai_usage_api_key_id]}


def fetch_daily_costs_usd(settings: Settings, *, start: date, end: date) -> list[DailyCost]:
    def parse(bucket: dict, day: date) -> list[DailyCost]:
        amount = sum(item.get("amount", {}).get("value", 0.0) for item in bucket.get("results", []))
        return [DailyCost(day=day, amount_usd=amount)]

    return _fetch_all_windows(
        settings,
        endpoint="organization/costs",
        start=start,
        end=end,
        extra_params=_key_filter(settings),
        parse_bucket=parse,
    )


def fetch_daily_usage(settings: Settings, *, start: date, end: date) -> list[DailyUsage]:
    """일별×모델별 실제 호출 수/입력토큰/출력토큰"""

    def parse(bucket: dict, day: date) -> list[DailyUsage]:
        return [
            DailyUsage(
                day=day,
                model=item.get("model") or "unknown",
                calls=item.get("num_model_requests", 0),
                input_tokens=item.get("input_tokens", 0),
                output_tokens=item.get("output_tokens", 0),
            )
            for item in bucket.get("results", [])
        ]

    return _fetch_all_windows(
        settings,
        endpoint="organization/usage/completions",
        start=start,
        end=end,
        extra_params={"group_by": ["model"], **_key_filter(settings)},
        parse_bucket=parse,
    )
