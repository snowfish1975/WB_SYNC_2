"""increase chrt_id to bigint in stocks and prices

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Increase chrt_id from INT4 to INT8 in stocks and prices."""
    op.alter_column('stocks', 'chrt_id', type_=sa.BigInteger(),
                     existing_type=sa.Integer())
    op.alter_column('prices', 'chrt_id', type_=sa.BigInteger(),
                     existing_type=sa.Integer())


def downgrade() -> None:
    """Revert chrt_id back to INT4."""
    op.alter_column('stocks', 'chrt_id', type_=sa.Integer(),
                     existing_type=sa.BigInteger())
    op.alter_column('prices', 'chrt_id', type_=sa.Integer(),
                     existing_type=sa.BigInteger())
