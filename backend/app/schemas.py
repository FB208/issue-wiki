from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import PaymentStatus, TaskStatus

T = TypeVar("T")


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class UserOut(OrmModel):
    id: int
    email: str | None
    phone: str | None
    nickname: str
    avatar_url: str | None
    role: str
    is_banned: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SendCodeRequest(BaseModel):
    target: str
    purpose: Literal["register", "reset"] = "register"


class RegisterRequest(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    nickname: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    avatar_url: str | None = None
    code: str = Field(min_length=4, max_length=12)

    @field_validator("phone")
    @classmethod
    def strip_phone(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class LoginRequest(BaseModel):
    account: str
    password: str


class ResetPasswordRequest(BaseModel):
    account: str
    code: str
    new_password: str = Field(min_length=8, max_length=128)


class UserProfileUpdate(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=1000)

    @field_validator("nickname")
    @classmethod
    def strip_nickname(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("昵称不能为空")
        return value

    @field_validator("avatar_url")
    @classmethod
    def strip_avatar_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


class PasswordUpdate(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TaskBase(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1)


class TaskCreateAdmin(TaskBase):
    sort_order: int | None = None
    start_amount: Decimal = Field(default=Decimal("0"), ge=0)
    status: TaskStatus = TaskStatus.pending_start
    is_hidden: bool = False


class TaskUpdateAdmin(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = None
    sort_order: int | None = None
    start_amount: Decimal | None = Field(default=None, ge=0)
    status: TaskStatus | None = None
    is_hidden: bool | None = None


class TaskDemandCreate(TaskBase):
    pass


class TaskOut(OrmModel):
    id: int
    name: str
    description: str
    sort_order: int
    start_amount: Decimal
    donated_amount: Decimal
    co_creator_count: int
    status: str
    status_label: str
    is_hidden: bool
    source: str
    creator_id: int | None
    github_repo: str | None = None
    github_issue_id: int | None = None
    github_issue_node_id: str | None = None
    github_issue_number: int | None = None
    github_issue_url: str | None = None
    github_author_login: str | None = None
    github_state: str | None = None
    github_updated_at: datetime | None = None
    last_github_sync_at: datetime | None = None
    github_sync_status: str
    github_sync_status_label: str
    github_sync_error: str | None = None
    created_at: datetime
    updated_at: datetime


class CommentCreate(BaseModel):
    content: str = Field(min_length=1)
    parent_id: int | None = None


class TaskCommentOut(OrmModel):
    id: int
    task_id: int
    user_id: int | None
    user_nickname: str
    content: str
    admin_reply: str | None
    github_comment_id: int | None = None
    github_author_login: str | None = None
    github_updated_at: datetime | None = None
    last_github_sync_at: datetime | None = None
    github_sync_error: str | None = None
    created_at: datetime
    updated_at: datetime


class PaymentConfigOut(BaseModel):
    channel: str
    xorpay_min_order_amount: Decimal


class PaymentSummaryOut(BaseModel):
    paid_amount: Decimal


class SponsorRankingItemOut(BaseModel):
    user_id: int | None
    nickname: str
    avatar_url: str | None = None
    amount: Decimal
    is_guest: bool = False


class SponsorCreate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)


class SponsorIntentOut(BaseModel):
    channel: str
    payment_url: str | None = None
    feature_id: str | None = None
    instructions: str
    order_id: int | None = None
    merchant_order_no: str | None = None
    amount: Decimal | None = None
    min_amount: Decimal | None = None
    status: str | None = None
    qr: str | None = None
    qr_image_url: str | None = None
    expires_in: int | None = None


class SponsorOrderOut(OrmModel):
    id: int
    task_id: int | None
    user_id: int | None
    is_guest: bool
    merchant_order_no: str
    afdian_order_no: str | None = None
    afdian_user_id: str | None = None
    afdian_user_private_id: str | None = None
    afdian_plan_id: str | None = None
    afdian_remark: str | None = None
    xorpay_aoid: str | None = None
    xorpay_qr: str | None = None
    xorpay_detail: str | None = None
    xorpay_pay_time: datetime | None = None
    amount: Decimal
    channel: str
    status: str
    created_at: datetime
    paid_at: datetime | None
    callback_at: datetime | None
    payment_url: str | None = None


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    parent_id: int | None = None
    sort_order: int | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    parent_id: int | None = None
    sort_order: int | None = None


class FolderOut(OrmModel):
    id: int
    parent_id: int | None
    name: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    content: str = Field(min_length=1)
    folder_id: int | None = None
    author: str = "生产力Mark"
    sort_order: int | None = None


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=220)
    content: str | None = None
    folder_id: int | None = None
    author: str | None = None
    sort_order: int | None = None


class DocumentOut(OrmModel):
    id: int
    folder_id: int | None
    title: str
    content: str
    author: str
    sort_order: int
    like_count: int = 0
    liked_by_me: bool = False
    comment_count: int = 0
    created_at: datetime
    updated_at: datetime


class DocumentCommentOut(OrmModel):
    id: int
    document_id: int
    parent_id: int | None = None
    parent_user_nickname: str | None = None
    parent_content: str | None = None
    user_id: int
    user_nickname: str
    content: str
    admin_reply: str | None
    created_at: datetime
    updated_at: datetime


class AdminCommentOut(BaseModel):
    id: int
    target: Literal["task", "document"]
    target_id: int
    user: str
    content: str
    admin_reply: str | None
    created_at: datetime


class LikeOut(BaseModel):
    liked: bool
    count: int


class HomeHeroOut(BaseModel):
    content: str


class HomeHeroUpdate(BaseModel):
    content: str = Field(min_length=1)


class SiteBrandingOut(BaseModel):
    logo_url: str | None
    title: str
    subtitle: str


class SiteBrandingUpdate(BaseModel):
    logo_url: str | None = None
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(default="", max_length=200)


class UploadOut(OrmModel):
    id: int
    original_filename: str
    file_type: str
    mime_type: str
    file_size: int
    object_key: str
    url: str
    created_at: datetime


class CommentAdminUpdate(BaseModel):
    admin_reply: str | None = None


class ReorderItem(BaseModel):
    id: int
    sort_order: int


class PaymentCallbackResult(BaseModel):
    status: PaymentStatus
    message: str


class GitHubSyncSummary(BaseModel):
    imported: int
    skipped: int
    failed: int
    comments_imported: int = 0
    errors: list[str] = Field(default_factory=list)
