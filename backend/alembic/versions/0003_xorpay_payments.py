"""add xorpay payment fields

Revision ID: 0003_xorpay_payments
Revises: 0002_home_hero
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_xorpay_payments"
down_revision: str | None = "0002_home_hero"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sponsor_orders", sa.Column("xorpay_aoid", sa.String(length=120), nullable=True))
    op.add_column("sponsor_orders", sa.Column("xorpay_qr", sa.String(length=1000), nullable=True))
    op.add_column("sponsor_orders", sa.Column("xorpay_detail", sa.Text(), nullable=True))
    op.add_column("sponsor_orders", sa.Column("xorpay_pay_time", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_sponsor_orders_xorpay_aoid"), "sponsor_orders", ["xorpay_aoid"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_sponsor_orders_xorpay_aoid"), table_name="sponsor_orders")
    op.drop_column("sponsor_orders", "xorpay_pay_time")
    op.drop_column("sponsor_orders", "xorpay_detail")
    op.drop_column("sponsor_orders", "xorpay_qr")
    op.drop_column("sponsor_orders", "xorpay_aoid")
