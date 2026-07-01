"""add document comment replies

Revision ID: 0004_document_comment_replies
Revises: 0003_github_sync
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_document_comment_replies"
down_revision: str | None = "0003_github_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_comments", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_document_comments_parent_id"), "document_comments", ["parent_id"], unique=False)
    op.create_foreign_key(
        "fk_document_comments_parent_id_document_comments",
        "document_comments",
        "document_comments",
        ["parent_id"],
        ["id"],
    )
    op.execute("UPDATE document_comments SET is_confirmed = 1")


def downgrade() -> None:
    op.drop_constraint("fk_document_comments_parent_id_document_comments", "document_comments", type_="foreignkey")
    op.drop_index(op.f("ix_document_comments_parent_id"), table_name="document_comments")
    op.drop_column("document_comments", "parent_id")
