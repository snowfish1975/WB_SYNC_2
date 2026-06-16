"""add rnp settings, costs, plans tables

Revision ID: c5d6e7f8a9b0
Revises: 8ead52702fbd
Create Date: 2026-06-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = '8ead52702fbd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('rnp_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cabinet_id', sa.String(length=32), nullable=False),
        sa.Column('usn_rate', sa.Float(), server_default='0.06', nullable=False),
        sa.Column('usn_rate_2025', sa.Float(), server_default='0.06', nullable=False),
        sa.Column('nds_rate', sa.Float(), server_default='0.07', nullable=False),
        sa.Column('nds_rate_2025', sa.Float(), server_default='0.07', nullable=False),
        sa.Column('usd_rate', sa.Float(), server_default='0', nullable=False),
        sa.Column('cny_rate', sa.Float(), server_default='0', nullable=False),
        sa.Column('paid_acceptance_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('localization_index', sa.Float(), server_default='1', nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cabinet_id', name='uq_rnp_settings_cabinet')
    )
    op.create_index(op.f('ix_rnp_settings_cabinet_id'), 'rnp_settings', ['cabinet_id'], unique=False)

    op.create_table('rnp_costs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cabinet_id', sa.String(length=32), nullable=False),
        sa.Column('supplier_article', sa.String(length=200), nullable=False),
        sa.Column('cost_rub', sa.Float(), server_default='0', nullable=False),
        sa.Column('currency', sa.String(length=10), server_default='RUB', nullable=False),
        sa.Column('manager', sa.String(length=100), nullable=True),
        sa.Column('product_type', sa.String(length=100), nullable=True),
        sa.Column('shipment_type', sa.String(length=100), nullable=True),
        sa.Column('min_price', sa.Float(), nullable=True),
        sa.Column('min_margin', sa.Float(), nullable=True),
        sa.Column('target_margin', sa.Float(), nullable=True),
        sa.Column('target_drr', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cabinet_id', 'supplier_article', name='uq_rnp_cost')
    )
    op.create_index(op.f('ix_rnp_costs_cabinet_id'), 'rnp_costs', ['cabinet_id'], unique=False)

    op.create_table('rnp_fixed_expenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cabinet_id', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('amount_monthly', sa.Float(), server_default='0', nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cabinet_id', 'name', name='uq_rnp_fixed_expense')
    )
    op.create_index(op.f('ix_rnp_fixed_expenses_cabinet_id'), 'rnp_fixed_expenses', ['cabinet_id'], unique=False)

    op.create_table('rnp_variable_expenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cabinet_id', sa.String(length=32), nullable=False),
        sa.Column('source_article', sa.String(length=200), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('percent', sa.Float(), server_default='0', nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cabinet_id', 'name', name='uq_rnp_variable_expense')
    )
    op.create_index(op.f('ix_rnp_variable_expenses_cabinet_id'), 'rnp_variable_expenses', ['cabinet_id'], unique=False)

    op.create_table('rnp_loan_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cabinet_id', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('amount_monthly', sa.Float(), server_default='0', nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cabinet_id', 'name', name='uq_rnp_loan_payment')
    )
    op.create_index(op.f('ix_rnp_loan_payments_cabinet_id'), 'rnp_loan_payments', ['cabinet_id'], unique=False)

    op.create_table('rnp_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cabinet_id', sa.String(length=32), nullable=False),
        sa.Column('month', sa.DateTime(), nullable=False),
        sa.Column('orders_amount', sa.Float(), server_default='0', nullable=False),
        sa.Column('orders_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('sales_minus_returns', sa.Float(), server_default='0', nullable=False),
        sa.Column('sales_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('returns_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('margin_rub', sa.Float(), server_default='0', nullable=False),
        sa.Column('margin_percent', sa.Float(), server_default='0', nullable=False),
        sa.Column('drr', sa.Float(), server_default='0', nullable=False),
        sa.Column('avg_price', sa.Float(), server_default='0', nullable=False),
        sa.Column('cost_of_goods', sa.Float(), server_default='0', nullable=False),
        sa.Column('logistics', sa.Float(), server_default='0', nullable=False),
        sa.Column('commission', sa.Float(), server_default='0', nullable=False),
        sa.Column('storage', sa.Float(), server_default='0', nullable=False),
        sa.Column('paid_acceptance', sa.Float(), server_default='0', nullable=False),
        sa.Column('promotion', sa.Float(), server_default='0', nullable=False),
        sa.Column('penalties', sa.Float(), server_default='0', nullable=False),
        sa.Column('nds', sa.Float(), server_default='0', nullable=False),
        sa.Column('profit', sa.Float(), server_default='0', nullable=False),
        sa.Column('spp', sa.Float(), server_default='0', nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cabinet_id', 'month', name='uq_rnp_plan')
    )
    op.create_index(op.f('ix_rnp_plans_cabinet_id'), 'rnp_plans', ['cabinet_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_rnp_plans_cabinet_id'), table_name='rnp_plans')
    op.drop_table('rnp_plans')
    op.drop_index(op.f('ix_rnp_loan_payments_cabinet_id'), table_name='rnp_loan_payments')
    op.drop_table('rnp_loan_payments')
    op.drop_index(op.f('ix_rnp_variable_expenses_cabinet_id'), table_name='rnp_variable_expenses')
    op.drop_table('rnp_variable_expenses')
    op.drop_index(op.f('ix_rnp_fixed_expenses_cabinet_id'), table_name='rnp_fixed_expenses')
    op.drop_table('rnp_fixed_expenses')
    op.drop_index(op.f('ix_rnp_costs_cabinet_id'), table_name='rnp_costs')
    op.drop_table('rnp_costs')
    op.drop_index(op.f('ix_rnp_settings_cabinet_id'), table_name='rnp_settings')
    op.drop_table('rnp_settings')
