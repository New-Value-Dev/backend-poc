from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def format_kst(dt: datetime) -> str:
    """DB에 UTC로 저장된 datetime을 알림 등 사용자 표시 문구용으로 KST 문자열로"""
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
