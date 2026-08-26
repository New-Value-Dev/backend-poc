"""벤치마크 채점 실행기

대상 document_version들의 섹션을 한 번만 읽어 인메모리로 청킹+임베딩하고, 
질문셋의 ground_truth(스니펫)와 대조해 Recall/MRR/NDCG를 낸다"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone

import numpy as np
import psutil

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.benchmark import BenchmarkResult
from app.repositories.benchmark_repository import (
    BenchmarkQuestionRepository,
    BenchmarkResultRepository,
    BenchmarkRunRepository,
)
from app.repositories.document_repository import DocumentVersionRepository
from app.repositories.embedding_repository import EmbeddingModelRepository
from app.services.benchmark.scoring import compute_score
from app.services.chunking.base import ChunkingParams
from app.services.chunking.semantic_chunker import build_semantic_chunks
from app.services.chunking.structure_chunker import build_structure_chunks
from app.services.embedding.factory import get_embedding_provider

logger = logging.getLogger(__name__)

# (content, document_id, page_start)
RankedChunk = tuple[str, int | None, int | None]


def _build_ephemeral_chunks(sections, provider, params: ChunkingParams):
    has_headings = any(s.section_type == "heading" for s in sections)
    strategy = params.strategy
    if strategy == "auto":
        strategy = "semantic" if not has_headings else "structure"
    if strategy == "structure":
        return build_structure_chunks(
            sections,
            max_chars=params.max_chars,
            overlap=params.overlap,
            min_chars=params.min_chars,
        )
    return build_semantic_chunks(
        sections,
        provider,
        max_chars=params.max_chars,
        overlap=params.overlap,
        sentence_window=params.sentence_window,
        breakpoint_percentile=params.breakpoint_percentile,
    )


def _is_relevant(content: str, document_id: int | None, ground_truth: list[dict]) -> bool:
    for gt in ground_truth:
        if gt.get("document_id") != document_id:
            continue
        snippet = (gt.get("expected_snippet") or "").strip()
        if snippet and snippet in content:
            return True
    return False


def _evaluate(ground_truth: list[dict], ranked: list[RankedChunk], top_k: int) -> tuple[dict, float, float]:
    window = ranked[:top_k]
    positions = [i for i, (content, doc_id, _) in enumerate(window) if _is_relevant(content, doc_id, ground_truth)]
    hit = {k: int(any(p < k for p in positions)) for k in (1, 3, 5)}
    rank = positions[0] + 1 if positions else None
    mrr = 1.0 / rank if rank else 0.0
    dcg = sum(1.0 / math.log2(p + 2) for p in positions[:top_k])
    return hit, mrr, min(dcg, 1.0)


def run_benchmark_task(run_id: int, model_ids: list[int]) -> None:
    db = SessionLocal()
    try:
        settings = get_settings()
        runs = BenchmarkRunRepository(db)
        results = BenchmarkResultRepository(db)
        questions_repo = BenchmarkQuestionRepository(db)
        models_repo = EmbeddingModelRepository(db)
        versions = DocumentVersionRepository(db)

        run = runs.get(run_id)
        if run is None:
            logger.warning("run_benchmark_task: run %s not found", run_id)
            return

        try:
            questions = questions_repo.list_by_dataset(run.dataset_id)
            params = ChunkingParams(**run.chunking_config)

            # 대상 버전들의 섹션 + document_id를 모델 순회 전에 한 번만 읽는다
            sections_by_version = {}
            document_by_version = {}
            for vid in run.target_document_ids:
                version = versions.get(vid)
                if version is None:
                    continue
                sections_by_version[vid] = versions.list_sections(vid)
                document_by_version[vid] = version.document_id

            for model_id in model_ids:
                _run_one_model(
                    db, results, models_repo, settings, run, questions, params,
                    sections_by_version, document_by_version, model_id,
                )

            run.status = "COMPLETED"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("benchmark run %s completed (%s models)", run_id, len(model_ids))
        except Exception as exc:
            db.rollback()
            run = runs.get(run_id)
            if run is not None:
                run.status = "FAILED"
                db.commit()
            logger.exception("benchmark run %s failed: %s", run_id, exc)
    finally:
        db.close()


def _run_one_model(
    db, results, models_repo, settings, run, questions, params,
    sections_by_version, document_by_version, model_id,
) -> None:
    model = models_repo.get(model_id)
    if model is None:
        return
    result = results.add(BenchmarkResult(run_id=run.id, embedding_model_id=model_id, status="RUNNING"))

    try:
        provider = get_embedding_provider(settings, model)

        load_start = time.perf_counter()
        provider.load()
        model_load_time_ms = (time.perf_counter() - load_start) * 1000
        ram_mb = psutil.Process().memory_info().rss / (1024 * 1024)

        pool: list[RankedChunk] = []
        embed_start = time.perf_counter()
        for vid, sections in sections_by_version.items():
            drafts = _build_ephemeral_chunks(sections, provider, params)
            doc_id = document_by_version.get(vid)
            pool.extend((d.content, doc_id, d.page_start) for d in drafts)

        contents = [c for c, _, _ in pool]
        if contents:
            vectors = np.asarray(provider.embed_documents(contents), dtype=np.float32)
        else:
            vectors = np.zeros((0, model.dimension), dtype=np.float32)
        embed_elapsed = max(time.perf_counter() - embed_start, 1e-6)
        throughput = len(contents) / embed_elapsed

        hits = {1: [], 3: [], 5: []}
        mrrs: list[float] = []
        ndcgs: list[float] = []
        latencies: list[float] = []
        details = []
        for q in questions:
            q_start = time.perf_counter()
            qvec = np.asarray(provider.embed_query(q.question), dtype=np.float32)
            latencies.append((time.perf_counter() - q_start) * 1000)

            if len(pool):
                sims = vectors @ qvec
                order = np.argsort(-sims)[: run.rag_top_k]
                ranked = [pool[i] for i in order]
            else:
                ranked = []

            hit, mrr, ndcg = _evaluate(q.ground_truth, ranked, run.rag_top_k)
            for k in (1, 3, 5):
                hits[k].append(hit[k])
            mrrs.append(mrr)
            ndcgs.append(ndcg)
            details.append(
                {
                    "question_id": q.id,
                    "hit_at_5": hit[5],
                    "top_result": ranked[0][0][:200] if ranked else None,
                }
            )

        n = max(len(questions), 1)
        metrics = {
            "recall_at_1": sum(hits[1]) / n,
            "recall_at_3": sum(hits[3]) / n,
            "recall_at_5": sum(hits[5]) / n,
            "mrr": sum(mrrs) / n,
            "ndcg": sum(ndcgs) / n,
            "avg_query_latency_ms": sum(latencies) / n if latencies else None,
            "embed_throughput_chunks_per_sec": throughput,
            "model_load_time_ms": model_load_time_ms,
            "ram_mb": ram_mb,
        }
        score = compute_score(metrics)

        result.status = "COMPLETED"
        for key, value in metrics.items():
            setattr(result, key, value)
        result.score = score
        result.question_details = {"items": details}
        db.commit()
    except Exception as exc:
        db.rollback()
        result = results.get(run.id, model_id)
        if result is not None:
            result.status = "FAILED"
            result.error = str(exc)[:2000]
            db.commit()
        logger.exception("benchmark result failed run=%s model=%s: %s", run.id, model_id, exc)
