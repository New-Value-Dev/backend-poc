"""add draft_answers to quiz_sessions

Revision ID: 69bf9354ce57
Revises: 7e08b38804fc
Create Date: 2026-08-27 13:54:16.735786

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '69bf9354ce57'
down_revision: Union[str, None] = '7e08b38804fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'quiz_sessions',
        sa.Column('draft_answers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('quiz_sessions', 'draft_answers')
