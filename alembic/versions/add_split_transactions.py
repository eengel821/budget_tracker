"""add_split_transactions

Revision ID: a1b2c3d4e5f6
Revises: 57dc43071454
Create Date: 2026-03-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '57dc43071454'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use defensive adds in case a partial migration left columns behind
    conn = op.get_bind()
    existing = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(transactions)"))]

    if 'is_split' not in existing:
        op.add_column('transactions',
            sa.Column('is_split', sa.Boolean(), nullable=False, server_default='0'))

    if 'parent_id' not in existing:
        op.add_column('transactions',
            sa.Column('parent_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('transactions', 'parent_id')
    op.drop_column('transactions', 'is_split')