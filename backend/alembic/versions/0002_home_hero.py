"""add home hero

Revision ID: 0002_home_hero
Revises: 0001_initial
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_home_hero"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_hero",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    home_hero_table = sa.table(
        "home_hero",
        sa.column("id", sa.Integer()),
        sa.column("content", sa.Text()),
    )
    op.bulk_insert(
        home_hero_table,
        [
            {
                "id": 1,
                "content": "## 用控制台方式管理开源任务、赞助订单和项目文档。\n\n用户提交需求，社区共创讨论，赞助推动优先级。第一版聚焦任务、文档、评论、订单和管理员后台。",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("home_hero")
