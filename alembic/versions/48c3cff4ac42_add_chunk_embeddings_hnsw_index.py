"""add chunk_embeddings hnsw index

Revision ID: 48c3cff4ac42
Revises: 72b852f975d6
Create Date: 2026-08-20 10:45:46.643561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48c3cff4ac42'
down_revision: Union[str, None] = '72b852f975d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 코사인 거리(<=>) 검색을 빠르게 하기 위한 근사 최근접 탐색 인덱스.
    # opclass(vector_cosine_ops)는 ChunkEmbeddingRepository.search() 가 쓰는
    # Vector.cosine_distance() 연산자(<=>)와 일치해야 인덱스가 실제로 쓰인다.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_embedding_hnsw "
        "ON chunk_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_embedding_hnsw")
