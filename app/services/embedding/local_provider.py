from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class LocalSentenceTransformerProvider:
    """sentence-transformers 로 로컬 in-process 임베딩.

    모델 로딩이 무거우므로(수 GB RAM, 첫 로드 시 수십 초~수 분) 프로세스당
    한 번만 로드되도록 factory 에서 lru_cache 로 감싼다.
    """

    def __init__(
        self,
        model_name: str,
        *,
        device: str,
        dimension: int,
        batch_size: int,
        max_seq_length: int,
        cache_folder: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer  # 지연 import(기동 속도)

        self._model = SentenceTransformer(model_name, device=device, cache_folder=cache_folder)
        self._model.max_seq_length = max_seq_length
        self._batch_size = batch_size
        self._lock = threading.Lock()  # encode()는 동시 호출 안전성이 보장되지 않음
        self.name = model_name
        self.dimension = dimension
        logger.info(
            "embedding model loaded: %s (device=%s, dim=%s)", model_name, device, dimension
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            vecs = self._model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return [v.tolist() for v in vecs]

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            vec = self._model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return vec.tolist()
