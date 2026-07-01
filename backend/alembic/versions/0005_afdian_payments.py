"""switch sponsor payments to afdian

Revision ID: 0005_afdian_payments
Revises: 0004_document_comment_replies
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_afdian_payments"
down_revision: str | None = "0004_document_comment_replies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("sponsor_orders", "task_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("sponsor_orders", sa.Column("afdian_order_no", sa.String(length=120), nullable=True))
    op.add_column("sponsor_orders", sa.Column("afdian_user_id", sa.String(length=120), nullable=True))
    op.add_column("sponsor_orders", sa.Column("afdian_user_private_id", sa.String(length=120), nullable=True))
    op.add_column("sponsor_orders", sa.Column("afdian_plan_id", sa.String(length=120), nullable=True))
    op.add_column("sponsor_orders", sa.Column("afdian_remark", sa.Text(), nullable=True))
    op.create_index(op.f("ix_sponsor_orders_afdian_order_no"), "sponsor_orders", ["afdian_order_no"], unique=True)
    op.create_index(op.f("ix_sponsor_orders_afdian_user_id"), "sponsor_orders", ["afdian_user_id"], unique=False)
    op.create_index(op.f("ix_sponsor_orders_afdian_user_private_id"), "sponsor_orders", ["afdian_user_private_id"], unique=False)
    op.create_index(op.f("ix_sponsor_orders_afdian_plan_id"), "sponsor_orders", ["afdian_plan_id"], unique=False)
    op.drop_index(op.f("ix_sponsor_orders_zpay_trade_no"), table_name="sponsor_orders")
    op.drop_column("sponsor_orders", "zpay_trade_no")


def downgrade() -> None:
    op.add_column("sponsor_orders", sa.Column("zpay_trade_no", sa.String(length=120), nullable=True))
    op.create_index(op.f("ix_sponsor_orders_zpay_trade_no"), "sponsor_orders", ["zpay_trade_no"], unique=False)
    op.drop_index(op.f("ix_sponsor_orders_afdian_plan_id"), table_name="sponsor_orders")
    op.drop_index(op.f("ix_sponsor_orders_afdian_user_private_id"), table_name="sponsor_orders")
    op.drop_index(op.f("ix_sponsor_orders_afdian_user_id"), table_name="sponsor_orders")
    op.drop_index(op.f("ix_sponsor_orders_afdian_order_no"), table_name="sponsor_orders")
    op.drop_column("sponsor_orders", "afdian_remark")
    op.drop_column("sponsor_orders", "afdian_plan_id")
    op.drop_column("sponsor_orders", "afdian_user_private_id")
    op.drop_column("sponsor_orders", "afdian_user_id")
    op.drop_column("sponsor_orders", "afdian_order_no")
    op.execute("DELETE FROM sponsor_orders WHERE task_id IS NULL")
    op.alter_column("sponsor_orders", "task_id", existing_type=sa.Integer(), nullable=False)
