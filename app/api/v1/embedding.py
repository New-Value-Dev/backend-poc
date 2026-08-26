from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.user import User
from app.repositories.document_repository import DocumentVersionRepository
from app.schemas.embedding import (
    ApplyBenchmarkRequest,
    ApplyBenchmarkResponse,
    BenchmarkDatasetCreate,
    BenchmarkDatasetRead,
    BenchmarkRunRead,
    EmbeddingJobRead,
    EmbeddingModelRead,
    MigrateRequest,
    RunBenchmarkRequest,
    RunBenchmarkResponse,
)
from app.services.benchmark.runner import run_benchmark_task
from app.services.benchmark_service import (
    BenchmarkDatasetNotFoundError,
    BenchmarkModelNotFoundError,
    BenchmarkResultNotReadyError,
    BenchmarkRunNotFoundError,
    BenchmarkRunNotReadyError,
    BenchmarkService,
    get_benchmark_service,
)
from app.services.embedding.migration import run_migration_task
from app.services.embedding_service import (
    EmbeddingJobNotFoundError,
    EmbeddingModelNotFoundError,
    EmbeddingService,
    MigrationTargetNotFoundError,
    get_embedding_service,
    run_reembed_task,
)

router = APIRouter(prefix="/embedding", tags=["embedding-lab"])

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
ADMIN_RESPONSE = {403: {"description": "관리자 권한 필요"}}
ModelIdPath = Annotated[int, Path(description="embedding_models.id", examples=[1])]
RunIdPath = Annotated[int, Path(description="benchmark_runs.id", examples=[1])]
JobIdPath = Annotated[int, Path(description="embedding_jobs.id", examples=[1])]


def _to_dataset_read(dataset, question_count: int) -> BenchmarkDatasetRead:
    read = BenchmarkDatasetRead.model_validate(dataset)
    read.question_count = question_count
    return read


# ── 모델 ──


@router.get(
    "/models",
    response_model=list[EmbeddingModelRead],
    summary="등록된 임베딩 모델 목록",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def list_models(
    service: EmbeddingService = Depends(get_embedding_service),
    _: User = Depends(require_admin),
) -> list[EmbeddingModelRead]:
    return [EmbeddingModelRead.model_validate(m) for m in service.list_models()]


@router.post(
    "/models/{model_id}/activate",
    response_model=EmbeddingModelRead,
    summary="이 모델을 활성 모델로 전환 (청킹 설정은 불변)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE, 404: {"description": "모델 없음"}},
)
def activate_model(
    model_id: ModelIdPath,
    service: EmbeddingService = Depends(get_embedding_service),
    _: User = Depends(require_admin),
) -> EmbeddingModelRead:
    try:
        model = service.activate_model(model_id)
    except EmbeddingModelNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model {model_id} not found") from None
    return EmbeddingModelRead.model_validate(model)


@router.post(
    "/models/{model_id}/reembed",
    response_model=EmbeddingJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="청킹은 그대로 두고 이 모델로 전체 document_chunks 재임베딩 (비동기)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE, 404: {"description": "모델 없음"}},
)
def reembed_model(
    model_id: ModelIdPath,
    background_tasks: BackgroundTasks,
    service: EmbeddingService = Depends(get_embedding_service),
    _: User = Depends(require_admin),
) -> EmbeddingJobRead:
    try:
        job = service.start_reembed(model_id)
    except EmbeddingModelNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model {model_id} not found") from None
    background_tasks.add_task(run_reembed_task, job.id, model_id)
    return EmbeddingJobRead.model_validate(job)


# ── 벤치마크 데이터셋 ──


@router.get(
    "/datasets",
    response_model=list[BenchmarkDatasetRead],
    summary="벤치마크 데이터셋 목록",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def list_datasets(
    service: BenchmarkService = Depends(get_benchmark_service),
    _: User = Depends(require_admin),
) -> list[BenchmarkDatasetRead]:
    return [_to_dataset_read(d, count) for d, count in service.list_datasets()]


@router.post(
    "/datasets",
    response_model=BenchmarkDatasetRead,
    status_code=status.HTTP_201_CREATED,
    summary="벤치마크 데이터셋 생성 (질문 + ground truth 스니펫 포함)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def create_dataset(
    body: BenchmarkDatasetCreate,
    service: BenchmarkService = Depends(get_benchmark_service),
    current_user: User = Depends(require_admin),
) -> BenchmarkDatasetRead:
    dataset = service.create_dataset(body, created_by=str(current_user.id))
    return _to_dataset_read(dataset, len(body.questions))


# ── 벤치마크 실행 ──


@router.get(
    "/benchmarks",
    response_model=list[BenchmarkRunRead],
    summary="벤치마크 run 목록 (모델별 결과 포함)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE},
)
def list_benchmarks(
    service: BenchmarkService = Depends(get_benchmark_service),
    _: User = Depends(require_admin),
) -> list[BenchmarkRunRead]:
    return [BenchmarkRunRead.model_validate(r) for r in service.list_runs()]


@router.post(
    "/benchmarks/run",
    response_model=RunBenchmarkResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="데이터셋 x 모델(x 청킹 파라미터) 조합으로 벤치마크 실행 (비동기)",
    responses={
        **AUTH_RESPONSES,
        **ADMIN_RESPONSE,
        404: {"description": "데이터셋 또는 모델 없음"},
    },
)
def run_benchmark(
    body: RunBenchmarkRequest,
    background_tasks: BackgroundTasks,
    service: BenchmarkService = Depends(get_benchmark_service),
    _: User = Depends(require_admin),
) -> RunBenchmarkResponse:
    override = body.chunking_config.model_dump(exclude_none=True) if body.chunking_config else None
    try:
        run = service.start_run(body.dataset_id, body.model_ids, override)
    except BenchmarkDatasetNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Dataset {body.dataset_id} not found"
        ) from None
    except BenchmarkModelNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Model {exc.model_id} not found"
        ) from None

    background_tasks.add_task(run_benchmark_task, run.id, body.model_ids)
    return RunBenchmarkResponse(run_id=run.id)


@router.get(
    "/benchmarks/{run_id}",
    response_model=BenchmarkRunRead,
    summary="벤치마크 run 상세 (진행 상황 폴링용)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE, 404: {"description": "run 없음"}},
)
def get_benchmark(
    run_id: RunIdPath,
    service: BenchmarkService = Depends(get_benchmark_service),
    _: User = Depends(require_admin),
) -> BenchmarkRunRead:
    try:
        run = service.get_run(run_id)
    except BenchmarkRunNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} not found") from None
    return BenchmarkRunRead.model_validate(run)


@router.post(
    "/benchmarks/{run_id}/apply",
    response_model=ApplyBenchmarkResponse,
    summary="검증된 (청킹설정, 모델) 조합을 운영에 적용 — 기존 문서 재처리는 트리거하지 않음",
    responses={
        **AUTH_RESPONSES,
        **ADMIN_RESPONSE,
        404: {"description": "run/result 없음"},
        409: {"description": "run이 아직 완료되지 않았거나 해당 모델 결과가 실패함"},
    },
)
def apply_benchmark(
    run_id: RunIdPath,
    body: ApplyBenchmarkRequest,
    service: BenchmarkService = Depends(get_benchmark_service),
    _: User = Depends(require_admin),
) -> ApplyBenchmarkResponse:
    try:
        config, model = service.apply_run(run_id, body.model_id)
    except BenchmarkRunNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} not found") from None
    except BenchmarkRunNotReadyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except BenchmarkResultNotReadyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return ApplyBenchmarkResponse(chunking_config_id=config.id, embedding_model_id=model.id)


# ── 마이그레이션(기존 문서 재청킹+임베딩) ──


@router.post(
    "/migrate",
    response_model=EmbeddingJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="관리자가 고른 기존 document_version을 재청킹+임베딩 (비동기)",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE, 404: {"description": "대상 버전 없음"}},
)
def migrate(
    body: MigrateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    service: EmbeddingService = Depends(get_embedding_service),
    _: User = Depends(require_admin),
) -> EmbeddingJobRead:
    versions = DocumentVersionRepository(db)
    try:
        job = service.start_migration(versions, body.document_version_ids)
    except MigrationTargetNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Document version {exc.version_id} not found"
        ) from None
    background_tasks.add_task(
        run_migration_task, job.id, body.document_version_ids, body.force_semantic
    )
    return EmbeddingJobRead.model_validate(job)


# ── 작업(job) 진행률 폴링 ──


@router.get(
    "/jobs/{job_id}",
    response_model=EmbeddingJobRead,
    summary="reembed/migrate 작업 진행률 폴링",
    responses={**AUTH_RESPONSES, **ADMIN_RESPONSE, 404: {"description": "작업 없음"}},
)
def get_job(
    job_id: JobIdPath,
    service: EmbeddingService = Depends(get_embedding_service),
    _: User = Depends(require_admin),
) -> EmbeddingJobRead:
    try:
        job = service.get_job(job_id)
    except EmbeddingJobNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} not found") from None
    return EmbeddingJobRead.model_validate(job)
