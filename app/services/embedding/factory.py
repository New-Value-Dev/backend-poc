from __future__ import annotations

import threading
from collections import OrderedDict

from app.core.config import Settings
from app.models.embedding_model import EmbeddingModel
from app.services.embedding.base import EmbeddingConfigError, EmbeddingProvider
from app.services.embedding.local_provider import SentenceTransformerProvider

_cache: "OrderedDict[str, EmbeddingProvider]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_key(model: EmbeddingModel, device: str) -> str:
    return f"{model.model_key}:{device}"


def get_embedding_provider(settings: Settings, model: EmbeddingModel) -> EmbeddingProvider:
    """등록된 EmbeddingModel 행 + Settings 로 provider 를 만들거나 캐시에서 재사용한다."""
    if settings.embedding_provider != "local":
        raise EmbeddingConfigError(
            f"지원하지 않는 embedding_provider: {settings.embedding_provider}"
        )

    key = _cache_key(model, settings.embedding_device)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached

        config = model.config or {}
        provider = SentenceTransformerProvider(
            model.model_key,
            model.model_name,
            expected_dimension=model.dimension,
            model_path=model.model_path,
            device=settings.embedding_device,
            cache_dir=settings.embedding_cache_dir,
            batch_size=settings.embedding_batch_size,
            max_seq_length=model.max_tokens or settings.embedding_max_seq_length,
            query_prefix=config.get("query_prefix", ""),
            doc_prefix=config.get("doc_prefix", ""),
        )
        _cache[key] = provider
        while len(_cache) > settings.embedding_max_loaded_models:
            _cache.popitem(last=False)
        return provider
