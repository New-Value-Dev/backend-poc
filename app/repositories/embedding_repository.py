from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from app.models.chunk_embedding import ChunkEmbedding
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.embedding_model import EmbeddingModel


class EmbeddingModelRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active(self) -> EmbeddingModel | None:
        return self.db.scalar(
            select(EmbeddingModel).where(EmbeddingModel.is_active.is_(True))
        )

    def get_or_create_active(
        self, *, model_key: str, model_name: str, dimension: int
    ) -> EmbeddingModel:
        """MVP는 활성 모델이 항상 1개라는 전제 — 없으면 만들고, 있으면 재활성화한다."""
        row = self.db.scalar(
            select(EmbeddingModel).where(EmbeddingModel.model_key == model_key)
        )
        if row is None:
            row = EmbeddingModel(
                model_key=model_key,
                model_name=model_name,
                dimension=dimension,
                status="ACTIVE",
                is_active=True,
            )
            self.db.add(row)
            self.db.flush()
        elif not row.is_active:
            row.is_active = True
        return row


class ChunkEmbeddingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_unembedded_chunks(
        self, version_id: int, embedding_model_id: int
    ) -> list[DocumentChunk]:
        """이 버전의 chunk 중 해당 모델의 embedding이 아직 없는 것들"""
        already = select(ChunkEmbedding.chunk_id).where(
            ChunkEmbedding.embedding_model_id == embedding_model_id
        )
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == version_id)
            .where(DocumentChunk.id.notin_(already))
            .order_by(DocumentChunk.chunk_index)
        )
        return list(self.db.scalars(stmt))

    def add_many(self, rows: list[ChunkEmbedding]) -> None:
        self.db.add_all(rows)
        self.db.flush()  # commit은 서비스가

    def search(
        self,
        query_vector: list[float],
        embedding_model_id: int,
        *,
        top_k: int,
        project_ids: list[int] | None = None,
        folder_ids: list[int] | None = None,
    ) -> list[Row]:
        """질의 벡터와 코사인 거리가 가까운 chunk 를 top_k 개 가져온다.
        distance 는 1 - cosine_similarity 이므로 score 변환은 호출부(서비스)에서 한다.
        """
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector)
        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.content,
                DocumentChunk.section_id,
                DocumentChunk.document_version_id,
                DocumentChunk.page_start,
                DocumentChunk.page_end,
                DocumentChunk.chunk_metadata,
                DocumentChunk.document_id,
                Document.name.label("document_name"),
                Document.project_id,
                Document.folder_id,
                distance.label("distance"),
            )
            .select_from(ChunkEmbedding)
            .join(DocumentChunk, ChunkEmbedding.chunk_id == DocumentChunk.id)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(ChunkEmbedding.embedding_model_id == embedding_model_id)
        )
        if project_ids:
            stmt = stmt.where(Document.project_id.in_(project_ids))
        if folder_ids:
            stmt = stmt.where(Document.folder_id.in_(folder_ids))
        stmt = stmt.order_by(distance).limit(top_k)
        return list(self.db.execute(stmt))

    def get_chunks_by_article_key(
        self,
        document_version_id: int,
        article_key: str,
        *,
        exclude_chunk_ids: set[int],
    ) -> list[Row]:
        """같은 조(article_key)에 속하지만 벡터 검색에 안 걸린 나머지 청크(형제)를
        chunk_index 순으로 가져온다. 컨텍스트 확장용 -- search() 와 동일한
        컬럼셋(distance 제외)을 써서 호출부에서 바로 이어붙일 수 있게 한다."""
        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.content,
                DocumentChunk.section_id,
                DocumentChunk.document_version_id,
                DocumentChunk.page_start,
                DocumentChunk.page_end,
                DocumentChunk.chunk_metadata,
                DocumentChunk.document_id,
                Document.name.label("document_name"),
                Document.project_id,
                Document.folder_id,
            )
            .select_from(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(DocumentChunk.document_version_id == document_version_id)
            .where(DocumentChunk.chunk_metadata["article_key"].astext == article_key)
        )
        if exclude_chunk_ids:
            stmt = stmt.where(DocumentChunk.id.notin_(exclude_chunk_ids))
        stmt = stmt.order_by(DocumentChunk.chunk_index)
        return list(self.db.execute(stmt))
