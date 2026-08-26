"""add hnsw index to chunk_embeddings

Revision ID: 48c3cff4ac42
Revises: c1a2b3d4e5f6
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '48c3cff4ac42'
down_revision: Union[str, None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # rag_repository.ChunkSearchRepository.search()가 cosine_distance(<=>)로 검색하므로
    # vector_cosine_ops를 사용. m/ef_construction은 pgvector 권장 기본값.
    op.execute(
        "CREATE INDEX ix_chunk_embeddings_embedding_hnsw "
        "ON chunk_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_chunk_embeddings_embedding_hnsw")
