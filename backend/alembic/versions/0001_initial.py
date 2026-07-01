"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("nickname", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("avatar_url", sa.String(length=1000), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_banned", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index(op.f("ix_users_is_banned"), "users", ["is_banned"], unique=False)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "document_folders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["document_folders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_folders_parent_id"), "document_folders", ["parent_id"], unique=False)
    op.create_index(op.f("ix_document_folders_sort_order"), "document_folders", ["sort_order"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("start_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sort_order"),
    )
    op.create_index(op.f("ix_tasks_creator_id"), "tasks", ["creator_id"], unique=False)
    op.create_index(op.f("ix_tasks_is_hidden"), "tasks", ["is_hidden"], unique=False)
    op.create_index(op.f("ix_tasks_name"), "tasks", ["name"], unique=False)
    op.create_index(op.f("ix_tasks_sort_order"), "tasks", ["sort_order"], unique=False)
    op.create_index(op.f("ix_tasks_source"), "tasks", ["source"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["folder_id"], ["document_folders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_folder_id"), "documents", ["folder_id"], unique=False)
    op.create_index(op.f("ix_documents_sort_order"), "documents", ["sort_order"], unique=False)
    op.create_index(op.f("ix_documents_title"), "documents", ["title"], unique=False)

    op.create_table(
        "task_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False),
        sa.Column("admin_reply", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_comments_is_confirmed"), "task_comments", ["is_confirmed"], unique=False)
    op.create_index(op.f("ix_task_comments_task_id"), "task_comments", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_comments_user_id"), "task_comments", ["user_id"], unique=False)

    op.create_table(
        "document_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False),
        sa.Column("admin_reply", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_comments_document_id"), "document_comments", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_comments_is_confirmed"), "document_comments", ["is_confirmed"], unique=False)
    op.create_index(op.f("ix_document_comments_user_id"), "document_comments", ["user_id"], unique=False)

    op.create_table(
        "sponsor_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("is_guest", sa.Boolean(), nullable=False),
        sa.Column("merchant_order_no", sa.String(length=80), nullable=False),
        sa.Column("zpay_trade_no", sa.String(length=120), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callback_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_order_no"),
    )
    op.create_index(op.f("ix_sponsor_orders_is_guest"), "sponsor_orders", ["is_guest"], unique=False)
    op.create_index(op.f("ix_sponsor_orders_merchant_order_no"), "sponsor_orders", ["merchant_order_no"], unique=False)
    op.create_index(op.f("ix_sponsor_orders_status"), "sponsor_orders", ["status"], unique=False)
    op.create_index(op.f("ix_sponsor_orders_task_id"), "sponsor_orders", ["task_id"], unique=False)
    op.create_index(op.f("ix_sponsor_orders_user_id"), "sponsor_orders", ["user_id"], unique=False)
    op.create_index(op.f("ix_sponsor_orders_zpay_trade_no"), "sponsor_orders", ["zpay_trade_no"], unique=False)

    op.create_table(
        "likes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("guest_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_type", "target_id", "guest_id", name="uq_likes_guest_target"),
        sa.UniqueConstraint("target_type", "target_id", "user_id", name="uq_likes_user_target"),
    )
    op.create_index(op.f("ix_likes_guest_id"), "likes", ["guest_id"], unique=False)
    op.create_index(op.f("ix_likes_target_id"), "likes", ["target_id"], unique=False)
    op.create_index("ix_likes_target", "likes", ["target_type", "target_id"], unique=False)
    op.create_index(op.f("ix_likes_user_id"), "likes", ["user_id"], unique=False)

    op.create_table(
        "upload_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(op.f("ix_upload_files_uploaded_by"), "upload_files", ["uploaded_by"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_upload_files_uploaded_by"), table_name="upload_files")
    op.drop_table("upload_files")
    op.drop_index(op.f("ix_likes_user_id"), table_name="likes")
    op.drop_index("ix_likes_target", table_name="likes")
    op.drop_index(op.f("ix_likes_target_id"), table_name="likes")
    op.drop_index(op.f("ix_likes_guest_id"), table_name="likes")
    op.drop_table("likes")
    op.drop_index(op.f("ix_sponsor_orders_zpay_trade_no"), table_name="sponsor_orders")
    op.drop_index(op.f("ix_sponsor_orders_user_id"), table_name="sponsor_orders")
    op.drop_index(op.f("ix_sponsor_orders_task_id"), table_name="sponsor_orders")
    op.drop_index(op.f("ix_sponsor_orders_status"), table_name="sponsor_orders")
    op.drop_index(op.f("ix_sponsor_orders_merchant_order_no"), table_name="sponsor_orders")
    op.drop_index(op.f("ix_sponsor_orders_is_guest"), table_name="sponsor_orders")
    op.drop_table("sponsor_orders")
    op.drop_index(op.f("ix_document_comments_user_id"), table_name="document_comments")
    op.drop_index(op.f("ix_document_comments_is_confirmed"), table_name="document_comments")
    op.drop_index(op.f("ix_document_comments_document_id"), table_name="document_comments")
    op.drop_table("document_comments")
    op.drop_index(op.f("ix_task_comments_user_id"), table_name="task_comments")
    op.drop_index(op.f("ix_task_comments_task_id"), table_name="task_comments")
    op.drop_index(op.f("ix_task_comments_is_confirmed"), table_name="task_comments")
    op.drop_table("task_comments")
    op.drop_index(op.f("ix_documents_title"), table_name="documents")
    op.drop_index(op.f("ix_documents_sort_order"), table_name="documents")
    op.drop_index(op.f("ix_documents_folder_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_tasks_status"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_source"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_sort_order"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_name"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_is_hidden"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_creator_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_document_folders_sort_order"), table_name="document_folders")
    op.drop_index(op.f("ix_document_folders_parent_id"), table_name="document_folders")
    op.drop_table("document_folders")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_is_banned"), table_name="users")
    op.drop_table("users")
