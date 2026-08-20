from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmbeddingError(Exception):
    """임베딩 생성 실패(모델 로드/추론 오류 등)."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """임베딩 provider 인터페이스. local 외 API 기반 provider 도 이 뒤에 붙는다."""

    name: str  # embedding_models.model_key 와 대응(로깅/식별용)
    dimension: int  # EMBEDDING_DIM(1024)과 일치해야 함

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """chunk 텍스트 목록 → 벡터 목록(입력 순서와 1:1 대응)."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """질의 1건 → 벡터 1개."""
        ...
