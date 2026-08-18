from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    """대시보드 응답 전용 베이스"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DashboardStats(_CamelModel):
    projects: int
    documents: int
    processing: int
    rag_today: int


class DocumentTypeCount(_CamelModel):
    label: str
    value: int


class PipelineStage(_CamelModel):
    # 프론트 DocStatus 와 동일한 값(UPLOADED/PARSING/.../FAILED). 라벨링은 프론트 담당.
    status: str
    count: int


class DashboardSummary(_CamelModel):
    stats: DashboardStats
    # 최근 7일치 처리 건수, 과거 → 오늘 순(마지막 원소가 오늘).
    weekly_processing: list[int]
    document_types: list[DocumentTypeCount]
    pipeline: list[PipelineStage]


class ActivityItem(_CamelModel):
    actor: str
    action: str
    target: str
    kind: str
    at: datetime
    target_type: str | None = None
    target_id: int | None = None
    target_alive: bool = False
