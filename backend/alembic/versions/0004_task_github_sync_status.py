"""add task github sync status

Revision ID: 0004_task_github_sync_status
Revises: 0003_xorpay_payments
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_task_github_sync_status"
down_revision: str | None = "0003_xorpay_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("github_sync_status", sa.String(length=32), server_default="unbound", nullable=False))
    op.create_index(op.f("ix_tasks_github_sync_status"), "tasks", ["github_sync_status"], unique=False)
    op.execute(
        """
        UPDATE tasks
        SET github_sync_status = CASE
            WHEN github_sync_error IS NOT NULL AND github_sync_error <> '' THEN 'error'
            WHEN github_issue_number IS NULL THEN 'unbound'
            WHEN last_github_sync_at IS NULL THEN 'pending'
            ELSE 'synced'
        END
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_github_sync_status"), table_name="tasks")
    op.drop_column("tasks", "github_sync_status")
