"""rework task sort order

Revision ID: 0005_task_sort_order_rework
Revises: 0004_task_github_sync_status
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_task_sort_order_rework"
down_revision: str | None = "0004_task_github_sync_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    drop_sort_order_unique_constraint()
    normalize_existing_sort_orders()


def downgrade() -> None:
    op.create_unique_constraint("uq_tasks_sort_order", "tasks", ["sort_order"])


def drop_sort_order_unique_constraint() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints("tasks"):
        if constraint.get("column_names") == ["sort_order"] and constraint.get("name"):
            op.drop_constraint(constraint["name"], "tasks", type_="unique")
            return
    for index in inspector.get_indexes("tasks"):
        if index.get("unique") and index.get("column_names") == ["sort_order"] and index.get("name"):
            op.drop_index(index["name"], table_name="tasks")
            return


def normalize_existing_sort_orders() -> None:
    bind = op.get_bind()
    tasks = sa.table(
        "tasks",
        sa.column("id", sa.Integer()),
        sa.column("status", sa.String(length=32)),
        sa.column("sort_order", sa.Integer()),
    )
    rows = bind.execute(
        sa.select(tasks.c.id, tasks.c.status).order_by(tasks.c.sort_order.asc(), tasks.c.id.asc())
    ).mappings()
    next_order = 1
    for row in rows:
        if row["status"] == "completed":
            sort_order = 0
        else:
            sort_order = next_order
            next_order += 1
        bind.execute(sa.update(tasks).where(tasks.c.id == row["id"]).values(sort_order=sort_order))
