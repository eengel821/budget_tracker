"""add_budget_month_to_transactions

Revision ID: add_budget_month
Revises: add_suggestion_columns
Create Date: 2026-05-01

Adds an optional budget_month column to the transactions table.

When set, the budget page uses this date instead of the transaction date
for month attribution. This supports the accrual pattern where a savings
reimbursement that arrives in April is attributed to March's budget because
that's when the expense was incurred.

The transactions page always displays and sorts by the real transaction date.
Only the budget page aggregations use budget_month.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_budget_month"
down_revision: Union[str, Sequence[str], None] = "add_suggestion_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(transactions)"))]

    if "budget_month" not in existing:
        op.add_column(
            "transactions",
            sa.Column("budget_month", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("transactions", "budget_month")
