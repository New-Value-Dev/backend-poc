"""add similarity_score to quiz_answers

Revision ID: 7575efe110eb
Revises: 6157fab639ca
Create Date: 2026-08-27 13:33:32.974569

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7575efe110eb'
down_revision: Union[str, None] = '6157fab639ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quiz_answers', sa.Column('similarity_score', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('quiz_answers', 'similarity_score')
