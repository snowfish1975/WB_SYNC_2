"""Add shelf_metrics and funnel_metrics tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-13 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'shelf_metrics',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cabinet_id', sa.String(32), nullable=False, index=True),
        sa.Column('nm_id', sa.Integer(), nullable=False, index=True),
        sa.Column('sa_name', sa.String(200), nullable=True),
        sa.Column('subject_name', sa.String(200), nullable=True),
        sa.Column('brand_name', sa.String(200), nullable=True),
        sa.Column('barcode', sa.String(50), nullable=True),
        sa.Column('date', sa.DateTime(), nullable=False, index=True),
        sa.Column('views', sa.Integer(), server_default='0'),
        sa.Column('cart_adds', sa.Integer(), server_default='0'),
        sa.Column('orders_count', sa.Integer(), server_default='0'),
        sa.Column('revenue', sa.Float(), server_default='0'),
        sa.Column('returns_count', sa.Integer(), server_default='0'),
        sa.Column('orders_wb', sa.Integer(), server_default='0'),
        sa.Column('open_card', sa.Integer(), server_default='0'),
        sa.Column('added_to_cart', sa.Integer(), server_default='0'),
        sa.Column('purchased', sa.Integer(), server_default='0'),
        sa.Column('conversion_tocart', sa.Float(), server_default='0'),
        sa.Column('conversion_tobuy', sa.Float(), server_default='0'),
        sa.Column('period_start', sa.DateTime(), nullable=True),
        sa.Column('period_end', sa.DateTime(), nullable=True),
        sa.Column('synced_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.UniqueConstraint('cabinet_id', 'nm_id', 'date', name='uq_shelf_metric'),
    )

    op.create_table(
        'funnel_metrics',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cabinet_id', sa.String(32), nullable=False, index=True),
        sa.Column('nm_id', sa.Integer(), nullable=False, index=True),
        sa.Column('sa_name', sa.String(200), nullable=True),
        sa.Column('subject_name', sa.String(200), nullable=True),
        sa.Column('brand_name', sa.String(200), nullable=True),
        sa.Column('date', sa.DateTime(), nullable=False, index=True),
        sa.Column('views', sa.Integer(), server_default='0'),
        sa.Column('cart_adds', sa.Integer(), server_default='0'),
        sa.Column('orders_count', sa.Integer(), server_default='0'),
        sa.Column('purchased', sa.Integer(), server_default='0'),
        sa.Column('revenue', sa.Float(), server_default='0'),
        sa.Column('returns_count', sa.Integer(), server_default='0'),
        sa.Column('conv_view_cart', sa.Float(), server_default='0'),
        sa.Column('conv_cart_order', sa.Float(), server_default='0'),
        sa.Column('conv_order_sale', sa.Float(), server_default='0'),
        sa.Column('conv_view_sale', sa.Float(), server_default='0'),
        sa.Column('period_start', sa.DateTime(), nullable=True),
        sa.Column('period_end', sa.DateTime(), nullable=True),
        sa.Column('synced_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.UniqueConstraint('cabinet_id', 'nm_id', 'date', name='uq_funnel_metric'),
    )


def downgrade() -> None:
    op.drop_table('funnel_metrics')
    op.drop_table('shelf_metrics')
