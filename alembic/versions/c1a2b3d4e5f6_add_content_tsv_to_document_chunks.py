"""add content_tsv to document_chunks

Revision ID: c1a2b3d4e5f6
Revises: 07bbfce32694
Create Date: 2026-08-25 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = '97198d524333'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # STORED 생성 컬럼 — ALTER TABLE 시점에 기존 행도 자동으로 채워진다(별도 백필 불필요).
    # 'simple' config는 IMMUTABLE이라 생성 컬럼 제약을 만족한다.
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
    )
    op.create_index(
        "ix_document_chunks_content_tsv",
        "document_chunks",
        ["content_tsv"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_content_tsv", table_name="document_chunks")
    op.execute("ALTER TABLE document_chunks DROP COLUMN content_tsv")
