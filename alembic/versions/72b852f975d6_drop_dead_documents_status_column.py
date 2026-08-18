"""drop dead documents.status column

Revision ID: 72b852f975d6
Revises: 1e199411435d
Create Date: 2026-08-16 14:58:27.633666

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72b852f975d6'
down_revision: Union[str, None] = '1e199411435d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 생성 시 "DRAFT" 로 박힌 뒤 아무도 갱신하지 않던 죽은 컬럼.
    # 살아 있는 처리 상태(document_versions.processing_status)와 이름이 겹쳐
    # 문서 목록 필터 버그를 냈다. 발행/보관 생명주기가 실제로 필요해지면
    # 그때 별도 이름(lifecycle_status 등)으로 다시 넣는다.
    op.drop_column('documents', 'status')


def downgrade() -> None:
    # 자동 생성본은 server_default 가 없어 기존 행이 있으면 NOT NULL 위반으로 실패한다.
    # 원래 모델 기본값이던 'DRAFT' 를 채운 뒤 default 를 떼어 원상태로 되돌린다.
    op.add_column(
        'documents',
        sa.Column(
            'status',
            sa.VARCHAR(length=30),
            autoincrement=False,
            nullable=False,
            server_default='DRAFT',
        ),
    )
    op.alter_column('documents', 'status', server_default=None)
