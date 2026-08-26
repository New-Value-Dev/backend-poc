from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.benchmark import (
    BenchmarkDataset,
    BenchmarkQuestion,
    BenchmarkResult,
    BenchmarkRun,
)


class BenchmarkDatasetRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[BenchmarkDataset]:
        return list(self.db.scalars(select(BenchmarkDataset).order_by(BenchmarkDataset.id.desc())))

    def get(self, dataset_id: int) -> BenchmarkDataset | None:
        return self.db.get(BenchmarkDataset, dataset_id)

    def add(self, dataset: BenchmarkDataset) -> BenchmarkDataset:
        """flush만 한다 — 질문을 함께 만드는 create_dataset()이 한 트랜잭션으로 commit한다."""
        self.db.add(dataset)
        self.db.flush()
        return dataset

    def count_questions(self, dataset_id: int) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(BenchmarkQuestion)
                .where(BenchmarkQuestion.dataset_id == dataset_id)
            )
            or 0
        )


class BenchmarkQuestionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_dataset(self, dataset_id: int) -> list[BenchmarkQuestion]:
        return list(
            self.db.scalars(
                select(BenchmarkQuestion)
                .where(BenchmarkQuestion.dataset_id == dataset_id)
                .order_by(BenchmarkQuestion.id)
            )
        )

    def add(self, question: BenchmarkQuestion) -> BenchmarkQuestion:
        self.db.add(question)
        self.db.flush()
        return question


class BenchmarkRunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[BenchmarkRun]:
        return list(
            self.db.scalars(
                select(BenchmarkRun)
                .options(selectinload(BenchmarkRun.results))
                .order_by(BenchmarkRun.id.desc())
            )
        )

    def get(self, run_id: int) -> BenchmarkRun | None:
        return self.db.scalar(
            select(BenchmarkRun)
            .options(selectinload(BenchmarkRun.results))
            .where(BenchmarkRun.id == run_id)
        )

    def add(self, run: BenchmarkRun) -> BenchmarkRun:
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run


class BenchmarkResultRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, run_id: int, embedding_model_id: int) -> BenchmarkResult | None:
        return self.db.scalar(
            select(BenchmarkResult).where(
                BenchmarkResult.run_id == run_id,
                BenchmarkResult.embedding_model_id == embedding_model_id,
            )
        )

    def add(self, result: BenchmarkResult) -> BenchmarkResult:
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result
