"""EmbeddingLab 벤치마크 + 운영 적용 서비스"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.benchmark import BenchmarkDataset, BenchmarkQuestion, BenchmarkRun
from app.models.chunking_config import ChunkingConfig
from app.models.embedding_model import EmbeddingModel
from app.repositories.benchmark_repository import (
    BenchmarkDatasetRepository,
    BenchmarkQuestionRepository,
    BenchmarkResultRepository,
    BenchmarkRunRepository,
)
from app.repositories.chunking_config_repository import ChunkingConfigRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.embedding_repository import EmbeddingModelRepository
from app.schemas.embedding import BenchmarkDatasetCreate
from app.services.chunking.base import ChunkingParams


class BenchmarkDatasetNotFoundError(Exception):
    def __init__(self, dataset_id: int) -> None:
        self.dataset_id = dataset_id
        super().__init__(f"Benchmark dataset {dataset_id} not found")


class BenchmarkRunNotFoundError(Exception):
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        super().__init__(f"Benchmark run {run_id} not found")


class BenchmarkModelNotFoundError(Exception):
    def __init__(self, model_id: int) -> None:
        self.model_id = model_id
        super().__init__(f"Embedding model {model_id} not found")


class BenchmarkRunNotReadyError(Exception):
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        super().__init__(f"Benchmark run {run_id} is not completed yet")


class BenchmarkResultNotReadyError(Exception):
    def __init__(self, run_id: int, model_id: int) -> None:
        self.run_id = run_id
        self.model_id = model_id
        super().__init__(f"No completed result for run {run_id} / model {model_id}")


class BenchmarkService:
    def __init__(
        self,
        db: Session,
        datasets: BenchmarkDatasetRepository,
        questions: BenchmarkQuestionRepository,
        runs: BenchmarkRunRepository,
        results: BenchmarkResultRepository,
        documents: DocumentRepository,
        embedding_models: EmbeddingModelRepository,
        chunking_configs: ChunkingConfigRepository,
        settings: Settings,
    ) -> None:
        self.db = db
        self.datasets = datasets
        self.questions = questions
        self.runs = runs
        self.results = results
        self.documents = documents
        self.embedding_models = embedding_models
        self.chunking_configs = chunking_configs
        self.settings = settings

    def list_datasets(self) -> list[tuple[BenchmarkDataset, int]]:
        return [(d, self.datasets.count_questions(d.id)) for d in self.datasets.list()]

    def create_dataset(self, data: BenchmarkDatasetCreate, *, created_by: str | None) -> BenchmarkDataset:
        dataset = self.datasets.add(
            BenchmarkDataset(
                name=data.name,
                description=data.description,
                project_id=data.project_id,
                created_by=created_by,
            )
        )
        for q in data.questions:
            self.questions.add(
                BenchmarkQuestion(
                    dataset_id=dataset.id,
                    question=q.question,
                    category=q.category,
                    ground_truth=q.ground_truth,
                )
            )
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def list_runs(self) -> list[BenchmarkRun]:
        return self.runs.list()

    def get_run(self, run_id: int) -> BenchmarkRun:
        run = self.runs.get(run_id)
        if run is None:
            raise BenchmarkRunNotFoundError(run_id)
        return run

    def _active_or_default_params(self) -> ChunkingParams:
        active = self.chunking_configs.get_active()
        if active is not None:
            return ChunkingParams(
                strategy=active.strategy,
                max_chars=active.chunk_max_chars,
                min_chars=active.chunk_min_chars,
                overlap=active.chunk_overlap_chars,
                sentence_window=active.sentence_window,
                breakpoint_percentile=active.breakpoint_percentile,
            )
        return ChunkingParams(
            strategy="auto" if self.settings.chunk_strategy_auto else "structure",
            max_chars=self.settings.chunk_max_chars,
            min_chars=self.settings.chunk_min_chars,
            overlap=self.settings.chunk_overlap_chars,
            sentence_window=self.settings.chunk_semantic_sentence_window,
            breakpoint_percentile=self.settings.chunk_semantic_breakpoint_percentile,
        )

    def _resolve_params(self, override: dict | None) -> ChunkingParams:
        base = self._active_or_default_params()
        if not override:
            return base
        return ChunkingParams(
            strategy=override.get("strategy", base.strategy),
            max_chars=override.get("chunk_max_chars", base.max_chars),
            min_chars=override.get("chunk_min_chars", base.min_chars),
            overlap=override.get("chunk_overlap_chars", base.overlap),
            sentence_window=override.get("sentence_window", base.sentence_window),
            breakpoint_percentile=override.get("breakpoint_percentile", base.breakpoint_percentile),
        )

    def start_run(
        self, dataset_id: int, model_ids: list[int], chunking_config: dict | None
    ) -> BenchmarkRun:
        """벤치마크 run을 만든다"""
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            raise BenchmarkDatasetNotFoundError(dataset_id)
        for model_id in model_ids:
            if self.embedding_models.get(model_id) is None:
                raise BenchmarkModelNotFoundError(model_id)

        questions = self.questions.list_by_dataset(dataset_id)
        document_ids = {gt["document_id"] for q in questions for gt in q.ground_truth}
        target_version_ids: list[int] = []
        for doc_id in document_ids:
            doc = self.documents.get(doc_id)
            if doc is not None and doc.current_version_id is not None:
                target_version_ids.append(doc.current_version_id)

        params = self._resolve_params(chunking_config)
        run = BenchmarkRun(
            dataset_id=dataset_id,
            chunking_config=asdict(params),
            rag_top_k=self.settings.rag_top_k,
            rag_min_score=self.settings.rag_min_score,
            target_document_ids=target_version_ids,
            status="RUNNING",
        )
        return self.runs.add(run)

    def apply_run(self, run_id: int, model_id: int) -> tuple[ChunkingConfig, EmbeddingModel]:
        """검증된 (청킹설정, 모델) 조합을 운영에 반영"""
        run = self.get_run(run_id)
        if run.status != "COMPLETED":
            raise BenchmarkRunNotReadyError(run_id)
        result = self.results.get(run_id, model_id)
        if result is None or result.status != "COMPLETED":
            raise BenchmarkResultNotReadyError(run_id, model_id)

        cfg = run.chunking_config
        new_config = self.chunking_configs.add(
            ChunkingConfig(
                name=f"benchmark-run-{run_id}",
                strategy=cfg["strategy"],
                chunk_max_chars=cfg["max_chars"],
                chunk_min_chars=cfg.get("min_chars", 0),
                chunk_overlap_chars=cfg["overlap"],
                sentence_window=cfg["sentence_window"],
                breakpoint_percentile=cfg["breakpoint_percentile"],
                source_benchmark_run_id=run_id,
            )
        )
        activated_config = self.chunking_configs.activate(new_config)

        model = self.embedding_models.get(model_id)
        assert model is not None  # start_run에서 이미 존재를 검증했다
        activated_model = self.embedding_models.activate(model)
        return activated_config, activated_model


def get_benchmark_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BenchmarkService:
    return BenchmarkService(
        db,
        BenchmarkDatasetRepository(db),
        BenchmarkQuestionRepository(db),
        BenchmarkRunRepository(db),
        BenchmarkResultRepository(db),
        DocumentRepository(db),
        EmbeddingModelRepository(db),
        ChunkingConfigRepository(db),
        settings,
    )
