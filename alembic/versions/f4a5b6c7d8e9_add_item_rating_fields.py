"""add subject_id, tag_name, tag_id, is_shadowed to item_ratings; nm_id to bigint

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-08-20 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add v2 API fields to item_ratings and widen nm_id."""
    op.alter_column('item_ratings', 'nm_id', type_=sa.BigInteger(),
                     existing_type=sa.Integer())
    op.add_column('item_ratings', sa.Column('subject_id', sa.BigInteger(), nullable=True))
    op.add_column('item_ratings', sa.Column('tag_name', sa.String(200), nullable=True))
    op.add_column('item_ratings', sa.Column('tag_id', sa.BigInteger(), nullable=True))
    op.add_column('item_ratings', sa.Column('is_shadowed', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Revert item_ratings changes."""
    op.drop_column('item_ratings', 'is_shadowed')
    op.drop_column('item_ratings', 'tag_id')
    op.drop_column('item_ratings', 'tag_name')
    op.drop_column('item_ratings', 'subject_id')
    op.alter_column('item_ratings', 'nm_id', type_=sa.Integer(),
                     existing_type=sa.BigInteger())
