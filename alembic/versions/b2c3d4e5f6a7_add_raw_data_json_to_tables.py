"""Add raw_data JSON column to data tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-13 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

tables = ['stocks', 'orders', 'prices', 'sales_reports', 'sales']


def upgrade() -> None:
    for table in tables:
        op.add_column(table, sa.Column('raw_data', sa.JSON(), nullable=True))


def downgrade() -> None:
    for table in tables:
        op.drop_column(table, 'raw_data')
