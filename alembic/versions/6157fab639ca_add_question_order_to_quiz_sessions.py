"""add question_order to quiz_sessions

Revision ID: 6157fab639ca
Revises: 5a44ea56bee7
Create Date: 2026-08-27 13:26:39.057083

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6157fab639ca'
down_revision: Union[str, None] = '5a44ea56bee7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'quiz_sessions',
        sa.Column('question_order', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('quiz_sessions', 'question_order')
