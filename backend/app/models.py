from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, Enum):
    admin = "admin"
    user = "user"


class TaskStatus(str, Enum):
    pending_review = "pending_review"
    pending_start = "pending_start"
    in_progress = "in_progress"
    completed = "completed"


TASK_STATUS_LABELS = {
    TaskStatus.pending_review.value: "待审核",
    TaskStatus.pending_start.value: "待启动",
    TaskStatus.in_progress.value: "进行中",
    TaskStatus.completed.value: "已完成",
}


class TaskSource(str, Enum):
    admin = "admin"
    user = "user"
    github = "github"


class GitHubSyncStatus(str, Enum):
    unbound = "unbound"
    pending = "pending"
    synced = "synced"
    error = "error"


GITHUB_SYNC_STATUS_LABELS = {
    GitHubSyncStatus.unbound.value: "未同步",
    GitHubSyncStatus.pending.value: "待同步",
    GitHubSyncStatus.synced.value: "已同步",
    GitHubSyncStatus.error.value: "同步失败",
}


class PaymentStatus(str, Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    closed = "closed"


class PaymentChannel(str, Enum):
    afdian = "afdian"
    xorpay = "xorpay"


class LikeTarget(str, Enum):
    document = "document"


class HomeHero(Base):
    __tablename__ = "home_hero"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SiteSetting(Base):
    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    nickname: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default=UserRole.user.value, index=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tasks: Mapped[list["Task"]] = relationship(back_populates="creator")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("github_repo", "github_issue_number", name="uq_tasks_github_repo_issue_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    description: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(index=True)
    start_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.pending_start.value, index=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default=TaskSource.admin.value, index=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    github_repo: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    github_issue_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    github_issue_node_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    github_issue_number: Mapped[int | None] = mapped_column(nullable=True, index=True)
    github_issue_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    github_author_login: Mapped[str | None] = mapped_column(String(120), nullable=True)
    github_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    github_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_github_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    github_sync_status: Mapped[str] = mapped_column(String(32), default=GitHubSyncStatus.unbound.value, index=True)
    github_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    creator: Mapped[User | None] = relationship(back_populates="tasks")
    comments: Mapped[list["TaskComment"]] = relationship(back_populates="task")
    orders: Mapped[list["SponsorOrder"]] = relationship(back_populates="task")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    admin_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_comment_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    github_author_login: Mapped[str | None] = mapped_column(String(120), nullable=True)
    github_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_github_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    github_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="comments")
    user: Mapped[User] = relationship()


class SponsorOrder(Base):
    __tablename__ = "sponsor_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    merchant_order_no: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    afdian_order_no: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    afdian_user_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    afdian_user_private_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    afdian_plan_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    afdian_remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    xorpay_aoid: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    xorpay_qr: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    xorpay_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    xorpay_pay_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    channel: Mapped[str] = mapped_column(String(32), default=PaymentChannel.afdian.value)
    status: Mapped[str] = mapped_column(String(32), default=PaymentStatus.pending.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    callback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task | None] = relationship(back_populates="orders")
    user: Mapped[User | None] = relationship()


class DocumentFolder(Base):
    __tablename__ = "document_folders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("document_folders.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    sort_order: Mapped[int] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    parent: Mapped["DocumentFolder | None"] = relationship(remote_side=[id])


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("document_folders.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(220), index=True)
    content: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(100), default="生产力Mark")
    sort_order: Mapped[int] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    folder: Mapped[DocumentFolder | None] = relationship()


class DocumentComment(Base):
    __tablename__ = "document_comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("document_comments.id"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    admin_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship()
    parent: Mapped["DocumentComment | None"] = relationship(remote_side=[id])
    user: Mapped[User] = relationship()


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (
        Index("ix_likes_target", "target_type", "target_id"),
        UniqueConstraint("target_type", "target_id", "user_id", name="uq_likes_user_target"),
        UniqueConstraint("target_type", "target_id", "guest_id", name="uq_likes_guest_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int] = mapped_column(index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    guest_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadFileRecord(Base):
    __tablename__ = "upload_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(32))
    mime_type: Mapped[str] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column()
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    url: Mapped[str] = mapped_column(String(1000))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GitHubSyncEvent(Base):
    __tablename__ = "github_sync_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    delivery_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(32), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="processing", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
