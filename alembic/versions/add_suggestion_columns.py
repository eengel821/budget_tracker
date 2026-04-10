"""add_suggestion_columns

Revision ID: add_suggestion_columns
Revises: a1b2c3d4e5f6
Create Date: 2026-04-08

Adds three columns to the transactions table to support the categorization
suggestion workflow:

  suggested_category_id  INTEGER (nullable) — FK to categories.id
  suggestion_confidence  REAL    (nullable) — softmax probability 0.0-1.0
  suggestion_source      TEXT    (nullable) — "keyword", "history", or "ml"

Note: SQLite does not support adding columns with FK constraints via
ALTER TABLE. The FK is omitted from the column definition here — SQLAlchemy
still enforces the relationship at the ORM level, and the column behaves
identically in practice. This matches the pattern used in add_split_transactions.py.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_suggestion_columns"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(transactions)"))]

    if "suggested_category_id" not in existing:
        op.add_column(
            "transactions",
            sa.Column("suggested_category_id", sa.Integer(), nullable=True),
        )

    if "suggestion_confidence" not in existing:
        op.add_column(
            "transactions",
            sa.Column("suggestion_confidence", sa.Float(), nullable=True),
        )

    if "suggestion_source" not in existing:
        op.add_column(
            "transactions",
            sa.Column("suggestion_source", sa.String(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("transactions", "suggestion_source")
    op.drop_column("transactions", "suggestion_confidence")
    op.drop_column("transactions", "suggested_category_id")