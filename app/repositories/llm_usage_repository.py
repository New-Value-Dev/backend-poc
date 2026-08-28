from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.llm_usage_log import LLMUsageLog


class LLMUsageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        feature: str,
        model: str,
        status: str,
        user_id: int | None = None,
        project_id: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: float | None = None,
        error_message: str | None = None,
    ) -> LLMUsageLog:
        log = LLMUsageLog(
            feature=feature,
            model=model,
            status=status,
            user_id=user_id,
            project_id=project_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            error_message=error_message,
        )
        self.db.add(log)
        self.db.commit()
        return log

    def list_page(
        self,
        *,
        feature: str | None = None,
        status: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[LLMUsageLog], int]:
        """관리자 성공/실패 로그 화면용 페이지네이션 조회"""
        stmt = select(LLMUsageLog)
        count_stmt = select(func.count()).select_from(LLMUsageLog)
        if feature is not None:
            stmt = stmt.where(LLMUsageLog.feature == feature)
            count_stmt = count_stmt.where(LLMUsageLog.feature == feature)
        if status is not None:
            stmt = stmt.where(LLMUsageLog.status == status)
            count_stmt = count_stmt.where(LLMUsageLog.status == status)
        stmt = stmt.order_by(LLMUsageLog.created_at.desc(), LLMUsageLog.id.desc())
        stmt = stmt.limit(limit).offset(offset)
        rows = list(self.db.scalars(stmt))
        total = self.db.scalar(count_stmt) or 0
        return rows, total

    def daily_totals(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, str, int, int, int, int]]:
        """(day, feature, prompt_tokens합, completion_tokens합, total_tokens합, 호출수) 일별 집계"""
        day = func.date(LLMUsageLog.created_at).label("day")
        stmt = (
            select(
                day,
                LLMUsageLog.feature,
                func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0),
                func.coalesce(func.sum(LLMUsageLog.total_tokens), 0),
                func.count(),
            )
            .where(LLMUsageLog.created_at >= start, LLMUsageLog.created_at < end)
            .group_by(day, LLMUsageLog.feature)
            .order_by(day)
        )
        return [tuple(row) for row in self.db.execute(stmt)]

    def status_counts(self, start: datetime, end: datetime) -> list[tuple[str, int]]:
        """기간 내 성공/실패 건수"""
        stmt = (
            select(LLMUsageLog.status, func.count())
            .where(LLMUsageLog.created_at >= start, LLMUsageLog.created_at < end)
            .group_by(LLMUsageLog.status)
        )
        return [(row[0], row[1]) for row in self.db.execute(stmt)]
