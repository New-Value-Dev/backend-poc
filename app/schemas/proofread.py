from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProofreadFindingRead(BaseModel):
    """교정 제안 1건(+ 원문 섹션/페이지 위치)."""

    original: str
    suggestion: str
    reason: str
    category: str
    section_id: int | None = None
    page_start: int | None = None
    page_end: int | None = None


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
