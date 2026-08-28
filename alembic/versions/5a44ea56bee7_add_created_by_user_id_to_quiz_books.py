"""add created_by_user_id to quiz_books

Revision ID: 5a44ea56bee7
Revises: 597bb43c455a
Create Date: 2026-08-27 13:21:29.740547

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a44ea56bee7'
down_revision: Union[str, None] = '597bb43c455a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'quiz_books', sa.Column('created_by_user_id', sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        'fk_quiz_books_created_by_user_id_users',
        'quiz_books', 'users',
        ['created_by_user_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_quiz_books_created_by_user_id_users', 'quiz_books', type_='foreignkey'
    )
    op.drop_column('quiz_books', 'created_by_user_id')
