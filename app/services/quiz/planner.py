"""출제 배치 계획 — 이 문서들에서 N문제를 LLM 호출 단위로"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.rag.retriever import RetrievedChunk


class NoChunksError(Exception):
    """대상 문서에 청크가 하나도 없다"""


@dataclass
class GenerationBatch:
    """LLM 호출 1회 단위 = 근거 청크 묶음 + 그 근거로 만들 문항 수"""

    document: Document
    chunks: list[RetrievedChunk]
    question_count: int


def allocate_counts(weights: list[int], total: int) -> list[int]:
    """total 을 weights(문서별 청크 수)에 비례 배분"""
    if total <= 0 or not weights:
        return [0] * len(weights)

    active = [i for i, w in enumerate(weights) if w > 0]
    if not active:
        return [0] * len(weights)

    # 문서 수가 요청 문항 수보다 많으면 전부에 1개씩 줄 수 없음
    if total <= len(active):
        out = [0] * len(weights)
        for i in sorted(active, key=lambda i: weights[i], reverse=True)[:total]:
            out[i] = 1
        return out

    pool = sum(weights[i] for i in active)
    out = [0] * len(weights)
    for i in active:
        out[i] = max(1, int(total * weights[i] / pool))

    # 최소 1 보장과 내림 때문에 합이 total 과 어긋날 수 있기때문에 큰 문서부터 조정
    order = sorted(active, key=lambda i: weights[i], reverse=True)
    while sum(out) > total:
        for i in reversed(order):
            if sum(out) <= total:
                break
            if out[i] > 1:
                out[i] -= 1
    while sum(out) < total:
        for i in order:
            if sum(out) >= total:
                break
            out[i] += 1
    return out


def split_evenly(items: list, parts: int) -> list[list]:
    """items 를 순서를 유지한 채 parts 개의 연속 구간으로 최대한 균등하게"""
    if parts <= 1 or len(items) <= 1:
        return [items] if items else []
    parts = min(parts, len(items))
    base, extra = divmod(len(items), parts)
    out: list[list] = []
    start = 0
    for i in range(parts):
        size = base + (1 if i < extra else 0)
        out.append(items[start : start + size])
        start += size
    return out


def _trim_to_budget(chunks: list[DocumentChunk], budget: int) -> list[DocumentChunk]:
    """배치 근거 총량이 budget 을 넘으면 구간 전체에 걸쳐 균등 샘플링해 줄인다."""
    if budget <= 0 or not chunks:
        return chunks
    total = sum(len(c.content or "") for c in chunks)
    if total <= budget:
        return chunks

    avg = max(1, total // len(chunks))
    keep = max(1, budget // avg)
    if keep >= len(chunks):
        return chunks
    step = len(chunks) / keep
    return [chunks[min(len(chunks) - 1, int(i * step))] for i in range(keep)]


def plan_batches(
    documents: list[tuple[Document, list[DocumentChunk]]],
    *,
    count: int,
    questions_per_call: int,
    batch_max_chars: int,
) -> list[GenerationBatch]:
    """(문서, 청크목록) 목록 → LLM 호출 단위 배치 목록"""
    usable = [(doc, chunks) for doc, chunks in documents if chunks]
    if not usable:
        raise NoChunksError("대상 문서에 청크가 없습니다 (아직 파싱/청킹 전입니다)")

    allocation = allocate_counts([len(chunks) for _, chunks in usable], count)

    batches: list[GenerationBatch] = []
    for (doc, chunks), assigned in zip(usable, allocation):
        if assigned <= 0:
            continue
        parts = max(1, math.ceil(assigned / max(1, questions_per_call)))
        groups = split_evenly(chunks, parts)
        # 청크 수가 적어 구간이 요청보다 적게 나오면, 남은 문항은 앞 구간들에 다시 분배
        per_group = allocate_counts([len(g) for g in groups], assigned)
        for group, group_count in zip(groups, per_group):
            if group_count <= 0:
                continue
            trimmed = _trim_to_budget(group, batch_max_chars)
            batches.append(
                GenerationBatch(
                    document=doc,
                    chunks=[
                        # 벡터 검색을 거치지 않았으므로 score 는 의미가 없다
                        RetrievedChunk(chunk=c, document=doc, score=1.0)
                        for c in trimmed
                    ],
                    question_count=group_count,
                )
            )
    return batches
