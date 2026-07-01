from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func
from sqlalchemy.orm import Session

from app.api.utils import page_payload, paginate_query, serialize_task, serialize_task_with_metrics, task_metrics_query
from app.dependencies import get_current_user, get_current_user_optional, get_db
from app.models import PaymentChannel, SponsorOrder, Task, TaskComment, TaskSource, TaskStatus, User
from app.schemas import CommentCreate, Page, SponsorCreate, SponsorIntentOut, SponsorOrderOut, TaskCommentOut, TaskDemandCreate, TaskOut
from app.services.github_sync import sync_comment_to_github_background
from app.services.payment import (
    PaymentConfigError,
    PaymentProviderError,
    PaymentValidationError,
    active_payment_channel,
    build_afdian_sponsor_url,
    build_task_feature_id,
    build_xorpay_qr_image_url,
    create_xorpay_sponsor_order,
    sponsor_instructions,
    xorpay_min_order_amount,
)
from app.services.task_ordering import normalize_task_sort_orders

router = APIRouter(prefix="/tasks", tags=["tasks"])


def serialize_task_comment(item: TaskComment) -> TaskCommentOut:
    author = item.user.nickname if item.user else item.github_author_login or "GitHub 用户"
    return TaskCommentOut(
        id=item.id,
        task_id=item.task_id,
        user_id=item.user_id,
        user_nickname=author,
        content=item.content,
        admin_reply=item.admin_reply,
        github_comment_id=item.github_comment_id,
        github_author_login=item.github_author_login,
        github_updated_at=item.github_updated_at,
        last_github_sync_at=item.last_github_sync_at,
        github_sync_error=item.github_sync_error,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=Page[TaskOut])
def list_tasks(
    name: str | None = None,
    status_list: list[str] | None = Query(default=None, alias="status"),
    sort_by: str = "sort_order",
    sort_order: str = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[TaskOut]:
    query, donated, _ = task_metrics_query(db)
    query = query.filter(Task.is_hidden.is_(False))
    if name:
        query = query.filter(Task.name.like(f"%{name}%"))
    statuses = [item for item in (status_list or []) if item]
    if statuses:
        query = query.filter(Task.status.in_(statuses))

    donated_col = func.coalesce(donated.c.donated_amount, 0)
    sort_map = {
        "sort_order": Task.sort_order,
        "name": Task.name,
        "start_amount": Task.start_amount,
        "donated_amount": donated_col,
    }
    if sort_by in sort_map:
        query = query.order_by(desc(sort_map[sort_by]) if sort_order == "desc" else asc(sort_map[sort_by]))
    else:
        query = query.order_by(Task.sort_order.asc())

    rows, total, page, page_size = paginate_query(query, page, page_size)
    items = [serialize_task_with_metrics(task, donated_amount, co_creator_count) for task, donated_amount, co_creator_count in rows]
    return page_payload(items, total, page, page_size)


@router.get("/my", response_model=Page[TaskOut])
def my_tasks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[TaskOut]:
    query, _, _ = task_metrics_query(db)
    query = query.filter(Task.creator_id == user.id, Task.is_hidden.is_(False)).order_by(Task.created_at.desc())
    rows, total, page, page_size = paginate_query(query, page, page_size)
    items = [serialize_task_with_metrics(task, donated_amount, co_creator_count) for task, donated_amount, co_creator_count in rows]
    return page_payload(items, total, page, page_size)


@router.get("/sponsor-orders/my", response_model=Page[SponsorOrderOut])
def my_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[SponsorOrderOut]:
    query = db.query(SponsorOrder).filter(SponsorOrder.user_id == user.id).order_by(SponsorOrder.created_at.desc())
    items, total, page, page_size = paginate_query(query, page, page_size)
    return page_payload(items, total, page, page_size)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    task = db.get(Task, task_id)
    if not task or task.is_hidden:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return serialize_task(db, task)


@router.post("/demands", response_model=TaskOut)
def create_demand(payload: TaskDemandCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaskOut:
    task = Task(
        name=payload.name,
        description=payload.description,
        sort_order=0,
        start_amount=Decimal("0"),
        status=TaskStatus.pending_review.value,
        source=TaskSource.user.value,
        creator_id=user.id,
    )
    db.add(task)
    db.flush()
    normalize_task_sort_orders(db, task)
    db.commit()
    db.refresh(task)
    return serialize_task(db, task)


@router.get("/{task_id}/comments", response_model=Page[TaskCommentOut])
def list_task_comments(
    task_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[TaskCommentOut]:
    query = db.query(TaskComment).filter(TaskComment.task_id == task_id, TaskComment.deleted_at.is_(None)).order_by(TaskComment.created_at.asc())
    comments, total, page, page_size = paginate_query(query, page, page_size)
    return page_payload([serialize_task_comment(item) for item in comments], total, page, page_size)


@router.post("/{task_id}/comments", response_model=TaskCommentOut)
def create_task_comment(
    task_id: int,
    payload: CommentCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskCommentOut:
    task = db.get(Task, task_id)
    if not task or task.is_hidden:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if task.status == TaskStatus.completed.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已完成任务不能继续共创")
    comment = TaskComment(task_id=task.id, user_id=user.id, content=payload.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    background_tasks.add_task(sync_comment_to_github_background, comment.id)
    return serialize_task_comment(comment)


@router.post("/{task_id}/sponsor", response_model=SponsorIntentOut)
def create_sponsor_order(
    task_id: int,
    payload: SponsorCreate | None = None,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> SponsorIntentOut:
    if user and user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被封禁")
    task = db.get(Task, task_id)
    if not task or task.is_hidden:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    try:
        channel = active_payment_channel()
    except PaymentConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if channel == PaymentChannel.afdian.value:
        payment_url = build_afdian_sponsor_url()
        if not payment_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="爱发电赞助链接未配置")
        feature_id = build_task_feature_id(task.id)
        return SponsorIntentOut(
            channel=PaymentChannel.afdian.value,
            payment_url=payment_url,
            feature_id=feature_id,
            instructions=sponsor_instructions(feature_id),
        )

    try:
        order, result = create_xorpay_sponsor_order(db, task, user, payload.amount if payload else None)
    except (PaymentConfigError, PaymentValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PaymentProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return SponsorIntentOut(
        channel=PaymentChannel.xorpay.value,
        instructions="请使用微信扫描二维码完成赞助，支付成功后系统会自动更新赞助金额。",
        order_id=order.id,
        merchant_order_no=order.merchant_order_no,
        amount=order.amount,
        min_amount=xorpay_min_order_amount(),
        status=order.status,
        qr=order.xorpay_qr,
        qr_image_url=build_xorpay_qr_image_url(order.xorpay_qr),
        expires_in=int(result.get("expires_in") or result.get("expire_in") or 0) or None,
    )
