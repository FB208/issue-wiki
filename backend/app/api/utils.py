from decimal import Decimal
from math import ceil

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import GITHUB_SYNC_STATUS_LABELS, GitHubSyncStatus, PaymentStatus, SponsorOrder, TASK_STATUS_LABELS, Task, TaskComment
from app.schemas import TaskOut

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def next_sort_order(db: Session, model: type, parent_field: str | None = None, parent_id: int | None = None) -> int:
    query = db.query(func.max(model.sort_order))
    if parent_field:
        query = query.filter(getattr(model, parent_field) == parent_id)
    current = query.scalar()
    return int(current or 0) + 1


def normalize_pagination(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> tuple[int, int]:
    return max(int(page or 1), 1), min(max(int(page_size or DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)


def page_payload(items: list, total: int, page: int, page_size: int) -> dict:
    pages = max(ceil(total / page_size), 1) if page_size else 1
    return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size, "pages": pages}


def paginate_query(query, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> tuple[list, int, int, int]:
    page, page_size = normalize_pagination(page, page_size)
    total = query.order_by(None).count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, int(total or 0), page, page_size


def task_metrics_query(db: Session):
    donated = (
        db.query(
            SponsorOrder.task_id.label("task_id"),
            func.coalesce(func.sum(SponsorOrder.amount), 0).label("donated_amount"),
        )
        .filter(SponsorOrder.status == PaymentStatus.paid.value)
        .group_by(SponsorOrder.task_id)
        .subquery()
    )
    co_creators = (
        db.query(
            TaskComment.task_id.label("task_id"),
            func.count(func.distinct(TaskComment.user_id)).label("co_creator_count"),
        )
        .filter(TaskComment.deleted_at.is_(None), TaskComment.user_id.isnot(None))
        .group_by(TaskComment.task_id)
        .subquery()
    )
    query = (
        db.query(
            Task,
            func.coalesce(donated.c.donated_amount, 0).label("donated_amount"),
            func.coalesce(co_creators.c.co_creator_count, 0).label("co_creator_count"),
        )
        .outerjoin(donated, donated.c.task_id == Task.id)
        .outerjoin(co_creators, co_creators.c.task_id == Task.id)
    )
    return query, donated, co_creators


def serialize_task(db: Session, task: Task) -> TaskOut:
    donated = db.query(func.coalesce(func.sum(SponsorOrder.amount), 0)).filter(
        SponsorOrder.task_id == task.id,
        SponsorOrder.status == PaymentStatus.paid.value,
    ).scalar()
    co_creator_count = db.query(func.count(func.distinct(TaskComment.user_id))).filter(
        TaskComment.task_id == task.id,
        TaskComment.deleted_at.is_(None),
    ).scalar()
    return serialize_task_with_metrics(task, Decimal(donated or 0), int(co_creator_count or 0))


def serialize_task_with_metrics(task: Task, donated_amount, co_creator_count) -> TaskOut:
    github_sync_status = task_github_sync_status(task)
    return TaskOut(
        id=task.id,
        name=task.name,
        description=task.description,
        sort_order=task.sort_order,
        start_amount=Decimal(task.start_amount),
        donated_amount=Decimal(donated_amount or 0),
        co_creator_count=int(co_creator_count or 0),
        status=task.status,
        status_label=TASK_STATUS_LABELS.get(task.status, task.status),
        is_hidden=task.is_hidden,
        source=task.source,
        creator_id=task.creator_id,
        github_repo=task.github_repo,
        github_issue_id=task.github_issue_id,
        github_issue_node_id=task.github_issue_node_id,
        github_issue_number=task.github_issue_number,
        github_issue_url=task.github_issue_url,
        github_author_login=task.github_author_login,
        github_state=task.github_state,
        github_updated_at=task.github_updated_at,
        last_github_sync_at=task.last_github_sync_at,
        github_sync_status=github_sync_status,
        github_sync_status_label=GITHUB_SYNC_STATUS_LABELS.get(github_sync_status, github_sync_status),
        github_sync_error=task.github_sync_error,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def task_github_sync_status(task: Task) -> str:
    if task.github_sync_status:
        return task.github_sync_status
    if task.github_sync_error:
        return GitHubSyncStatus.error.value
    if task.github_issue_number is None:
        return GitHubSyncStatus.unbound.value
    if task.last_github_sync_at is None:
        return GitHubSyncStatus.pending.value
    return GitHubSyncStatus.synced.value
