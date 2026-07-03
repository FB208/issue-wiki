"""add site settings

Revision ID: 0006_site_settings
Revises: 0005_task_sort_order_rework
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_site_settings"
down_revision: str | None = "0005_task_sort_order_rework"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("logo_url", sa.String(length=1000), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("subtitle", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    site_settings_table = sa.table(
        "site_settings",
        sa.column("id", sa.Integer()),
        sa.column("logo_url", sa.String()),
        sa.column("title", sa.String()),
        sa.column("subtitle", sa.String()),
    )
    op.bulk_insert(
        site_settings_table,
        [
            {
                "id": 1,
                "logo_url": None,
                "title": 易标投标工具箱",
                "subtitle": "使用文档",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("site_settings")
