"""merge rnp tables with user fields

Revision ID: fc5600d6ee37
Revises: 81ced3f50bdc, c5d6e7f8a9b0
Create Date: 2026-06-16 20:53:23.707637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc5600d6ee37'
down_revision: Union[str, Sequence[str], None] = ('81ced3f50bdc', 'c5d6e7f8a9b0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
