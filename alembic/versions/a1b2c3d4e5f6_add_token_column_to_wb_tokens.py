"""Add token column to wb_tokens table

Revision ID: a1b2c3d4e5f6
Revises: 4b7f10b50d64
Create Date: 2026-06-13 11:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4b7f10b50d64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('wb_tokens', sa.Column('token', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('wb_tokens', 'token')
