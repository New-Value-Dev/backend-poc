from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    model_key: str
    model_name: str
    model_version: str | None
    dimension: int
    max_tokens: int | None
    status: str
    is_active: bool
    config: dict[str, Any] | None
    created_at: datetime


class EmbeddingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    embedding_model_id: int | None
    status: str
    target_count: int
    processed_count: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class MigrateRequest(BaseModel):
    document_version_ids: list[int] = Field(min_length=1)
    force_semantic: bool = False


class BenchmarkQuestionCreate(BaseModel):
    question: str
    category: str | None = None
    # [{"document_id": int, "expected_snippet": str, "page_start": int|None}, ...]
    ground_truth: list[dict[str, Any]] = Field(min_length=1)


class BenchmarkDatasetCreate(BaseModel):
    name: str
    description: str | None = None
    project_id: int | None = None
    questions: list[BenchmarkQuestionCreate] = Field(min_length=1)


class BenchmarkQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    category: str | None
    ground_truth: list[dict[str, Any]]


class BenchmarkDatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    project_id: int | None
    created_at: datetime
    question_count: int = 0


class ChunkingConfigOverride(BaseModel):
    """runBenchmark 요청에 실린 청킹 파라미터 override — 전부 optional, 생략 시 활성 설정 사용."""

    strategy: str | None = None
    chunk_max_chars: int | None = None
    # structure 청킹 하한(같은 heading 아래 인접 본문을 뭉칠 최소 길이). 0이면 뭉치지 않는다.
    chunk_min_chars: int | None = Field(default=None, ge=0)
    chunk_overlap_chars: int | None = None
    sentence_window: int | None = None
    breakpoint_percentile: float | None = None


class RunBenchmarkRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    dataset_id: int
    model_ids: list[int] = Field(min_length=1)
    chunking_config: ChunkingConfigOverride | None = None


class RunBenchmarkResponse(BaseModel):
    run_id: int


class ApplyBenchmarkRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: int


class ApplyBenchmarkResponse(BaseModel):
    chunking_config_id: int
    embedding_model_id: int


class BenchmarkResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    embedding_model_id: int
    status: str
    recall_at_1: float | None
    recall_at_3: float | None
    recall_at_5: float | None
    mrr: float | None
    ndcg: float | None
    avg_query_latency_ms: float | None
    embed_throughput_chunks_per_sec: float | None
    model_load_time_ms: float | None
    ram_mb: float | None
    score: float | None
    error: str | None


class BenchmarkRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    chunking_config: dict[str, Any]
    rag_top_k: int
    rag_min_score: float
    status: str
    created_at: datetime
    finished_at: datetime | None
    results: list[BenchmarkResultRead] = []
