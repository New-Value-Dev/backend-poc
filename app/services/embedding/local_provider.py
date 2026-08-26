from __future__ import annotations

import logging
import threading

from app.services.embedding.base import EmbeddingConfigError, EmbeddingError

logger = logging.getLogger(__name__)


class SentenceTransformerProvider:
    """sentence-transformers 로컬 모델을 백엔드 프로세스 안에서 직접 로드하는 provider.

    생성자에서는 로드하지 않는다(무거움) — load()에서 지연 로딩한다.
    """

    def __init__(
        self,
        model_key: str,
        model_name: str,
        *,
        expected_dimension: int,
        model_path: str | None = None,
        device: str = "cpu",
        cache_dir: str | None = None,
        batch_size: int = 16,
        max_seq_length: int = 512,
        query_prefix: str = "",
        doc_prefix: str = "",
    ) -> None:
        self.name = model_key
        self.dimension = expected_dimension
        self._model_name = model_name
        self._source = model_path or model_name
        self._device = device
        self._cache_dir = cache_dir
        self._batch_size = batch_size
        self._max_seq_length = max_seq_length
        self._query_prefix = query_prefix
        self._doc_prefix = doc_prefix
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover
                raise EmbeddingConfigError(
                    "sentence-transformers 패키지가 설치되어 있지 않습니다"
                ) from exc
            try:
                model = SentenceTransformer(
                    self._source, cache_folder=self._cache_dir, device=self._device
                )
                model.max_seq_length = self._max_seq_length
            except Exception as exc:
                raise EmbeddingError(
                    f"임베딩 모델 로드 실패 ({self._source}): {exc}"
                ) from exc

            actual_dim = model.get_sentence_embedding_dimension()
            if actual_dim != self.dimension:
                raise EmbeddingConfigError(
                    f"'{self._model_name}' 모델의 실제 차원({actual_dim})이 "
                    f"등록된 차원({self.dimension})과 다릅니다"
                )
            self._model = model
            logger.info("embedding model loaded: %s (dim=%s, device=%s)",
                        self._model_name, actual_dim, self._device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.load()
        if not texts:
            return []
        prefixed = [f"{self._doc_prefix}{t}" for t in texts] if self._doc_prefix else texts
        vectors = self._model.encode(
            prefixed,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        self.load()
        prefixed = f"{self._query_prefix}{text}" if self._query_prefix else text
        vector = self._model.encode(
            [prefixed],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vector[0].tolist()

    def get_dimension(self) -> int:
        return self.dimension

    def get_model_name(self) -> str:
        return self._model_name
