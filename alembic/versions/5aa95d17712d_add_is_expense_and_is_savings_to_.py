"""add_is_expense_and_is_savings_to_categories

Revision ID: 5aa95d17712d
Revises: 
Create Date: 2026-03-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = '5aa95d17712d'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('categories', sa.Column('is_expense', sa.Boolean(), nullable=True))
    op.add_column('categories', sa.Column('is_savings', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('categories', 'is_savings')
    op.drop_column('categories', 'is_expense')