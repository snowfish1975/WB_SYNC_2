"""initial tables

Revision ID: 4b7f10b50d64
Revises: 
Create Date: 2026-06-12 18:52:04.533913

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4b7f10b50d64'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
