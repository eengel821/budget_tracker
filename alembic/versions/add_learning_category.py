"""add_learning_category

Revision ID: add_learning_category
Revises: add_budget_month
Create Date: 2026-10-10

Adds an independent ML learning category to transactions. Existing confirmed
categories are copied so current training labels are preserved.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_learning_category"
down_revision: Union[str, Sequence[str], None] = "add_budget_month"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(transactions)"))]

    if "learning_category_id" not in existing:
        op.add_column(
            "transactions",
            sa.Column("learning_category_id", sa.Integer(), nullable=True),
        )
        conn.execute(sa.text(
            "UPDATE transactions SET learning_category_id = category_id "
            "WHERE category_id IS NOT NULL"
        ))


def downgrade() -> None:
    op.drop_column("transactions", "learning_category_id")