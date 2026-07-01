"""add github issue sync

Revision ID: 0003_github_sync
Revises: 0002_home_hero
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_github_sync"
down_revision: str | None = "0002_home_hero"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("github_repo", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("github_issue_id", sa.BigInteger(), nullable=True))
    op.add_column("tasks", sa.Column("github_issue_node_id", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("github_issue_number", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("github_issue_url", sa.String(length=1000), nullable=True))
    op.add_column("tasks", sa.Column("github_author_login", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("github_state", sa.String(length=32), nullable=True))
    op.add_column("tasks", sa.Column("github_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("last_github_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("github_sync_error", sa.Text(), nullable=True))
    op.create_index(op.f("ix_tasks_github_repo"), "tasks", ["github_repo"], unique=False)
    op.create_index(op.f("ix_tasks_github_issue_id"), "tasks", ["github_issue_id"], unique=True)
    op.create_index(op.f("ix_tasks_github_issue_number"), "tasks", ["github_issue_number"], unique=False)
    op.create_unique_constraint("uq_tasks_github_repo_issue_number", "tasks", ["github_repo", "github_issue_number"])

    op.add_column("task_comments", sa.Column("github_comment_id", sa.BigInteger(), nullable=True))
    op.add_column("task_comments", sa.Column("github_author_login", sa.String(length=120), nullable=True))
    op.add_column("task_comments", sa.Column("github_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("task_comments", sa.Column("last_github_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("task_comments", sa.Column("github_sync_error", sa.Text(), nullable=True))
    op.alter_column("task_comments", "user_id", existing_type=sa.Integer(), nullable=True)
    op.create_index(op.f("ix_task_comments_github_comment_id"), "task_comments", ["github_comment_id"], unique=True)

    op.create_table(
        "github_sync_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("delivery_id", sa.String(length=120), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=True),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id"),
    )
    op.create_index(op.f("ix_github_sync_events_action"), "github_sync_events", ["action"], unique=False)
    op.create_index(op.f("ix_github_sync_events_delivery_id"), "github_sync_events", ["delivery_id"], unique=False)
    op.create_index(op.f("ix_github_sync_events_direction"), "github_sync_events", ["direction"], unique=False)
    op.create_index(op.f("ix_github_sync_events_event_type"), "github_sync_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_github_sync_events_status"), "github_sync_events", ["status"], unique=False)
    op.create_index(op.f("ix_github_sync_events_target_id"), "github_sync_events", ["target_id"], unique=False)
    op.create_index(op.f("ix_github_sync_events_target_type"), "github_sync_events", ["target_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_github_sync_events_target_type"), table_name="github_sync_events")
    op.drop_index(op.f("ix_github_sync_events_target_id"), table_name="github_sync_events")
    op.drop_index(op.f("ix_github_sync_events_status"), table_name="github_sync_events")
    op.drop_index(op.f("ix_github_sync_events_event_type"), table_name="github_sync_events")
    op.drop_index(op.f("ix_github_sync_events_direction"), table_name="github_sync_events")
    op.drop_index(op.f("ix_github_sync_events_delivery_id"), table_name="github_sync_events")
    op.drop_index(op.f("ix_github_sync_events_action"), table_name="github_sync_events")
    op.drop_table("github_sync_events")

    op.drop_index(op.f("ix_task_comments_github_comment_id"), table_name="task_comments")
    op.alter_column("task_comments", "user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("task_comments", "github_sync_error")
    op.drop_column("task_comments", "last_github_sync_at")
    op.drop_column("task_comments", "github_updated_at")
    op.drop_column("task_comments", "github_author_login")
    op.drop_column("task_comments", "github_comment_id")

    op.drop_constraint("uq_tasks_github_repo_issue_number", "tasks", type_="unique")
    op.drop_index(op.f("ix_tasks_github_issue_number"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_github_issue_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_github_repo"), table_name="tasks")
    op.drop_column("tasks", "github_sync_error")
    op.drop_column("tasks", "last_github_sync_at")
    op.drop_column("tasks", "github_updated_at")
    op.drop_column("tasks", "github_state")
    op.drop_column("tasks", "github_author_login")
    op.drop_column("tasks", "github_issue_url")
    op.drop_column("tasks", "github_issue_number")
    op.drop_column("tasks", "github_issue_node_id")
    op.drop_column("tasks", "github_issue_id")
    op.drop_column("tasks", "github_repo")
