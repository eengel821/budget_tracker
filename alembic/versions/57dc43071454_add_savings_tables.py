"""add_savings_tables

Revision ID: 57dc43071454
Revises: 5aa95d17712d
Create Date: 2026-03-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '57dc43071454'
down_revision: Union[str, Sequence[str], None] = '5aa95d17712d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'savings_transactions',
        sa.Column('id',           sa.Integer(),  nullable=False),
        sa.Column('date',         sa.Date(),     nullable=False),
        sa.Column('amount',       sa.Float(),    nullable=False),
        sa.Column('description',  sa.String(),   nullable=False),
        sa.Column('notes',        sa.String(),   nullable=True),
        sa.Column('is_allocated', sa.Boolean(),  nullable=False, default=False),
        sa.Column('account_id',   sa.Integer(),  nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_savings_transactions_id', 'savings_transactions', ['id'], unique=False)

    op.create_table(
        'savings_allocations',
        sa.Column('id',                     sa.Integer(), nullable=False),
        sa.Column('savings_transaction_id', sa.Integer(), nullable=False),
        sa.Column('category_id',            sa.Integer(), nullable=False),
        sa.Column('amount',                 sa.Float(),   nullable=False),
        sa.ForeignKeyConstraint(['savings_transaction_id'], ['savings_transactions.id']),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_savings_allocations_id', 'savings_allocations', ['id'], unique=False)

    op.create_table(
        'allocation_templates',
        sa.Column('id',         sa.Integer(), nullable=False),
        sa.Column('name',       sa.String(),  nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, default=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_allocation_templates_id', 'allocation_templates', ['id'], unique=False)

    op.create_table(
        'allocation_template_items',
        sa.Column('id',          sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('amount',      sa.Float(),   nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['allocation_templates.id']),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_allocation_template_items_id', 'allocation_template_items', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_allocation_template_items_id', table_name='allocation_template_items')
    op.drop_table('allocation_template_items')
    op.drop_index('ix_allocation_templates_id', table_name='allocation_templates')
    op.drop_table('allocation_templates')
    op.drop_index('ix_savings_allocations_id', table_name='savings_allocations')
    op.drop_table('savings_allocations')
    op.drop_index('ix_savings_transactions_id', table_name='savings_transactions')
    op.drop_table('savings_transactions')