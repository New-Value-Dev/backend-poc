from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class FindingStatus(str, Enum):
    """사용자가 finding을 승인/반려했는지 상태"""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ProofreadFindingRead(BaseModel):
    """교정 제안 1건(+ 원문 섹션/페이지 위치)."""

    id: str = ""
    original: str
    suggestion: str
    reason: str
    category: str
    section_id: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    status: FindingStatus = FindingStatus.PENDING


class ProofreadResult(BaseModel):
    """proofread 실행 결과. ai_analysis_results 1건에 대응."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    document_version_id: int
    analysis_type: str
    status: str
    provider: str | None
    findings: list[ProofreadFindingRead]
    sections_scanned: int
    error: str | None = None
    created_at: datetime
    applied_version_id: int | None = None
    applied_at: datetime | None = None


class AnalysisSummary(BaseModel):
    """AI 분석 이력 목록 항목(결과 본문 제외, 메타만)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    document_version_id: int
    analysis_type: str
    status: str
    provider: str | None
    created_at: datetime


class FindingStatusUpdate(BaseModel):
    """finding 1건의 승인/반려 상태 변경 요청."""

    status: FindingStatus


class ApplyCorrectionsResponse(BaseModel):
    """승인된 finding들을 원본 파일에 반영해 새 버전을 만든 결과."""

    analysis_id: int
    document_id: int
    new_version_id: int
    new_version_no: int
    applied_count: int
    skipped_count: int
    skipped_reasons: list[str]
