from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmbeddingError(Exception):
    """임베딩 호출 실패(모델 로드/추론 등)."""


class EmbeddingConfigError(EmbeddingError):
    """Embedding provider 설정 문제(예: 차원 불일치)."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """로컬/원격 임베딩 provider 공통 인터페이스. docs/DESIGN.md §12 시그니처."""

    name: str
    dimension: int

    def load(self) -> None:
        """모델 가중치를 메모리에 올린다. 무거운 작업이라 생성자와 분리한다."""
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """저장용(문서) 텍스트를 배치로 임베딩한다. 반환은 입력 순서와 1:1 대응."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """검색 쿼리 1건을 임베딩한다."""
        ...

    def get_dimension(self) -> int:
        ...

    def get_model_name(self) -> str:
        ...
