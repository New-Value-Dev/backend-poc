from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings
from app.models.chunk_embedding import EMBEDDING_DIM
from app.services.embedding.base import EmbeddingProvider
from app.services.embedding.local_provider import LocalSentenceTransformerProvider


@lru_cache
def _load_local(
    model_name: str,
    device: str,
    batch_size: int,
    max_seq_length: int,
    cache_folder: str,
) -> LocalSentenceTransformerProvider:
    """모델을 프로세스당 한 번만 로드(수 GB RAM/수 초~수십 초 로딩 비용)."""
    return LocalSentenceTransformerProvider(
        model_name,
        device=device,
        dimension=EMBEDDING_DIM,
        batch_size=batch_size,
        max_seq_length=max_seq_length,
        cache_folder=cache_folder,
    )


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """설정에 따라 임베딩 provider 를 고른다.

    현재는 "local"만 지원 — 나중에 API 기반/별도 서비스로 확장할 때
    이 함수만 갈아끼우면 된다(embedding/base.py 의 EmbeddingProvider 계약만 지키면 됨).
    """
    if settings.embedding_provider == "local":
        return _load_local(
            settings.embedding_model_name,
            settings.embedding_device,
            settings.embedding_batch_size,
            settings.embedding_max_seq_length,
            settings.embedding_cache_dir,
        )
    raise ValueError(f"unsupported embedding_provider: {settings.embedding_provider}")
