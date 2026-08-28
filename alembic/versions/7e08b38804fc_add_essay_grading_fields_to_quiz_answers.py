"""add essay grading fields to quiz_answers

Revision ID: 7e08b38804fc
Revises: 7575efe110eb
Create Date: 2026-08-27 13:41:59.953136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e08b38804fc'
down_revision: Union[str, None] = '7575efe110eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quiz_answers', sa.Column('score', sa.Float(), nullable=True))
    op.add_column('quiz_answers', sa.Column('feedback', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('quiz_answers', 'feedback')
    op.drop_column('quiz_answers', 'score')
