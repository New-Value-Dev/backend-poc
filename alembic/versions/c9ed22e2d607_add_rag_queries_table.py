"""add rag_queries table

Revision ID: c9ed22e2d607
Revises: 48c3cff4ac42
Create Date: 2026-08-20 10:45:59.890407

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9ed22e2d607'
down_revision: Union[str, None] = '48c3cff4ac42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ai_analysis_results 를 재사용하지 않는 이유: 그 테이블은 document_id/
    # document_version_id 가 NOT NULL FK 라 "문서 1개당 분석 1건"을 전제하는데,
    # RAG 질의는 여러 문서/프로젝트에 걸칠 수 있어 이 모양이 안 맞는다.
    op.create_table(
        'rag_queries',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('project_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('folder_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=True),
        sa.Column('embedding_model_id', sa.BigInteger(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['embedding_model_id'], ['embedding_models.id'],
            name=op.f('fk_rag_queries_embedding_model_id_embedding_models'),
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rag_queries')),
    )


def downgrade() -> None:
    op.drop_table('rag_queries')
