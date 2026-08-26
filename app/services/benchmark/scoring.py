"""벤치마크 결과를 하나의 합성 점수(0~100)로 낸다
절대 기준이 없는 MVP 단계라 latency/RAM처럼 낮을수록 좋은 지표는 단순 역수 스케일로 정규화
"""

from __future__ import annotations

DEFAULT_WEIGHTS = {
    "accuracy": 0.60,
    "performance": 0.15,
    "latency": 0.10,
    "ram": 0.10,
    "ops": 0.05,
}

# 정규화 기준값 — 이 값 이상이면 100으로 clamp
_THROUGHPUT_CEILING = 100.0 # chunks/sec
_LATENCY_FLOOR_MS = 100.0 # 이보다 빠르면 만점
_RAM_FLOOR_MB = 1000.0 # 이보다 적으면 만점
_RAM_CEILING_MB = 8000.0 # 이보다 많으면 0점


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def compute_score(
    metrics: dict[str, float | None],
    *,
    weights: dict[str, float] | None = None,
    ops_score: float = 100.0,
) -> float:
    weights = weights or DEFAULT_WEIGHTS

    recall = metrics.get("recall_at_5") or 0.0
    accuracy_score = _clamp(recall * 100)

    throughput = metrics.get("embed_throughput_chunks_per_sec") or 0.0
    performance_score = _clamp(throughput / _THROUGHPUT_CEILING * 100)

    latency_ms = metrics.get("avg_query_latency_ms")
    latency_score = 100.0 if not latency_ms else _clamp(_LATENCY_FLOOR_MS / latency_ms * 100)

    ram_mb = metrics.get("ram_mb")
    if not ram_mb:
        ram_score = 100.0
    else:
        span = _RAM_CEILING_MB - _RAM_FLOOR_MB
        ram_score = _clamp(100 - (ram_mb - _RAM_FLOOR_MB) / span * 100)

    return (
        accuracy_score * weights["accuracy"]
        + performance_score * weights["performance"]
        + latency_score * weights["latency"]
        + ram_score * weights["ram"]
        + _clamp(ops_score) * weights["ops"]
    )
