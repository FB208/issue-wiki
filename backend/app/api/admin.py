from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func, literal, or_
from sqlalchemy.orm import Session

from app.api.documents import serialize_document
from app.api.utils import next_sort_order, page_payload, paginate_query, serialize_task, serialize_task_with_metrics, task_metrics_query
from app.dependencies import get_current_admin, get_db
from app.models import Document, DocumentComment, DocumentFolder, GitHubSyncStatus, Like, LikeTarget, PaymentStatus, SponsorOrder, Task, TaskComment, TaskSource, TaskStatus, User, UserRole
from app.schemas import AdminCommentOut, CommentAdminUpdate, CommentCreate, DocumentCreate, DocumentOut, DocumentUpdate, FolderCreate, FolderOut, FolderUpdate, GitHubSyncSummary, HomeHeroOut, HomeHeroUpdate, Page, ReorderItem, SiteBrandingOut, SiteBrandingUpdate, SponsorOrderOut, TaskCommentOut, TaskCreateAdmin, TaskOut, TaskUpdateAdmin, UserOut
from app.services.github_sync import GitHubSyncError, delete_comment_from_github_background, sync_comment_to_github_background, sync_historical_issues, sync_task_to_github_background
from app.services.home_hero import get_home_hero, save_home_hero
from app.services.site_settings import get_site_settings, save_site_settings
from app.services.task_ordering import normalize_task_sort_orders

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])


@router.get("/tasks", response_model=Page[TaskOut])
def admin_list_tasks(
    name: str | None = None,
    status_list: list[str] | None = Query(default=None, alias="status"),
    sort_by: str = "sort_order",
    sort_order: str = "asc",
    source_list: list[str] | None = Query(default=None, alias="source"),
    visibility: Literal["all", "visible", "hidden"] = "all",
    github_sync: Literal["all", "unbound", "pending", "synced", "error"] = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[TaskOut]:
    query, donated, _ = task_metrics_query(db)
    if name:
        query = query.filter(Task.name.like(f"%{name}%"))
    statuses = [item for item in (status_list or []) if item]
    sources = [item for item in (source_list or []) if item]
    if statuses:
        query = query.filter(Task.status.in_(statuses))
    if sources:
        query = query.filter(Task.source.in_(sources))
    if visibility == "visible":
        query = query.filter(Task.is_hidden.is_(False))
    elif visibility == "hidden":
        query = query.filter(Task.is_hidden.is_(True))
    if github_sync == "unbound":
        query = query.filter(Task.github_sync_status == GitHubSyncStatus.unbound.value)
    elif github_sync == "pending":
        query = query.filter(Task.github_sync_status == GitHubSyncStatus.pending.value)
    elif github_sync == "synced":
        query = query.filter(Task.github_sync_status == GitHubSyncStatus.synced.value)
    elif github_sync == "error":
        query = query.filter(Task.github_sync_status == GitHubSyncStatus.error.value)
    donated_col = func.coalesce(donated.c.donated_amount, 0)
    sort_map = {
        "sort_order": Task.sort_order,
        "name": Task.name,
        "start_amount": Task.start_amount,
        "donated_amount": donated_col,
    }
    sort_col = sort_map.get(sort_by, Task.sort_order)
    sort_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)
    rows, total, page, page_size = paginate_query(query.order_by(sort_expr, Task.id.asc()), page, page_size)
    items = [serialize_task_with_metrics(task, donated_amount, co_creator_count) for task, donated_amount, co_creator_count in rows]
    return page_payload(items, total, page, page_size)


@router.post("/tasks", response_model=TaskOut)
def admin_create_task(payload: TaskCreateAdmin, db: Session = Depends(get_db)) -> TaskOut:
    task = Task(
        name=payload.name,
        description=payload.description,
        sort_order=0,
        start_amount=payload.start_amount,
        status=payload.status.value,
        is_hidden=payload.is_hidden,
        source=TaskSource.admin.value,
    )
    db.add(task)
    db.flush()
    normalize_task_sort_orders(db, task, payload.sort_order)
    db.commit()
    db.refresh(task)
    return serialize_task(db, task)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def admin_update_task(
    task_id: int,
    payload: TaskUpdateAdmin,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TaskOut:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    previous_status = task.status
    previous_sort_order = task.sort_order
    data = payload.model_dump(exclude_unset=True)
    sort_order_requested = "sort_order" in data and data["sort_order"] is not None
    requested_sort_order = data.pop("sort_order", None)
    if "status" in data and data["status"] is not None:
        data["status"] = data["status"].value
    changed_fields = set()
    for key, value in data.items():
        if getattr(task, key) != value:
            changed_fields.add(key)
            setattr(task, key, value)
    normalize_task_sort_orders(db, task, task_requested_sort_order(task, previous_status, previous_sort_order, requested_sort_order, sort_order_requested))
    db.commit()
    db.refresh(task)
    schedule_task_github_sync_after_admin_update(db, background_tasks, task, previous_status, changed_fields)
    return serialize_task(db, task)


@router.post("/tasks/reorder")
def admin_reorder_tasks(items: list[ReorderItem], db: Session = Depends(get_db)) -> dict[str, str]:
    requested_orders = {item.id: item.sort_order for item in items}
    tasks = db.query(Task).filter(Task.id.in_(requested_orders)).all()
    for task in tasks:
        if task.status != TaskStatus.completed.value:
            task.sort_order = requested_orders[task.id]
    normalize_task_sort_orders(db)
    db.commit()
    return {"message": "排序已更新"}


def task_requested_sort_order(
    task: Task,
    previous_status: str,
    previous_sort_order: int,
    requested_sort_order: int | None,
    sort_order_requested: bool,
) -> int | None:
    if task.status == TaskStatus.completed.value:
        return None
    if sort_order_requested:
        return requested_sort_order
    if previous_status == TaskStatus.completed.value:
        return None
    return previous_sort_order


@router.get("/tasks/{task_id}", response_model=TaskOut)
def admin_get_task(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return serialize_task(db, task)


@router.get("/tasks/{task_id}/comments", response_model=Page[TaskCommentOut])
def admin_list_task_comments(
    task_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[TaskCommentOut]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    query = db.query(TaskComment).filter(TaskComment.task_id == task_id, TaskComment.deleted_at.is_(None)).order_by(TaskComment.created_at.asc())
    comments, total, page, page_size = paginate_query(query, page, page_size)
    return page_payload([serialize_admin_task_comment(item) for item in comments], total, page, page_size)


@router.post("/tasks/{task_id}/comments", response_model=TaskCommentOut)
def admin_create_task_comment(
    task_id: int,
    payload: CommentCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TaskCommentOut:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    comment = TaskComment(task_id=task.id, user_id=user.id, content=payload.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    background_tasks.add_task(sync_comment_to_github_background, comment.id)
    return serialize_admin_task_comment(comment)


@router.get("/home-hero", response_model=HomeHeroOut)
def admin_get_home_hero(db: Session = Depends(get_db)) -> HomeHeroOut:
    return get_home_hero(db)


@router.put("/home-hero", response_model=HomeHeroOut)
def admin_update_home_hero(payload: HomeHeroUpdate, db: Session = Depends(get_db)) -> HomeHeroOut:
    return save_home_hero(db, payload)


@router.get("/site-settings", response_model=SiteBrandingOut)
def admin_get_site_settings(db: Session = Depends(get_db)) -> SiteBrandingOut:
    return get_site_settings(db)


@router.put("/site-settings", response_model=SiteBrandingOut)
def admin_update_site_settings(payload: SiteBrandingUpdate, db: Session = Depends(get_db)) -> SiteBrandingOut:
    return save_site_settings(db, payload)


@router.post("/github/sync-issues", response_model=GitHubSyncSummary)
def admin_sync_github_issues(db: Session = Depends(get_db)) -> GitHubSyncSummary:
    try:
        return GitHubSyncSummary(**sync_historical_issues(db))
    except GitHubSyncError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/folders", response_model=Page[FolderOut])
def admin_list_folders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[FolderOut]:
    items, total, page, page_size = paginate_query(db.query(DocumentFolder).order_by(DocumentFolder.sort_order.asc()), page, page_size)
    return page_payload(items, total, page, page_size)


def validate_folder_parent(db: Session, folder_id: int | None, parent_id: int | None) -> None:
    if parent_id is None:
        return
    if folder_id is not None and parent_id == folder_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上级文件夹不能选择自身")
    parent = db.get(DocumentFolder, parent_id)
    if not parent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上级文件夹不存在")
    while folder_id is not None and parent.parent_id is not None:
        if parent.parent_id == folder_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上级文件夹不能选择子文件夹")
        parent = db.get(DocumentFolder, parent.parent_id)
        if not parent:
            return


@router.post("/folders", response_model=FolderOut)
def admin_create_folder(payload: FolderCreate, db: Session = Depends(get_db)) -> DocumentFolder:
    validate_folder_parent(db, None, payload.parent_id)
    folder = DocumentFolder(name=payload.name, parent_id=payload.parent_id, sort_order=payload.sort_order or next_sort_order(db, DocumentFolder))
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.put("/folders/{folder_id}", response_model=FolderOut)
def admin_update_folder(folder_id: int, payload: FolderUpdate, db: Session = Depends(get_db)) -> DocumentFolder:
    folder = db.get(DocumentFolder, folder_id)
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件夹不存在")
    if "parent_id" in payload.model_fields_set:
        validate_folder_parent(db, folder_id, payload.parent_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(folder, key, value)
    db.commit()
    db.refresh(folder)
    return folder


@router.delete("/folders/{folder_id}")
def admin_delete_folder(folder_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    folder = db.get(DocumentFolder, folder_id)
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件夹不存在")
    if db.query(DocumentFolder.id).filter(DocumentFolder.parent_id == folder_id).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先删除或移动子文件夹")
    if db.query(Document.id).filter(Document.folder_id == folder_id).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先删除或移动该文件夹下的文档")
    db.delete(folder)
    db.commit()
    return {"message": "文件夹已删除"}


@router.get("/documents", response_model=Page[DocumentOut])
def admin_list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[DocumentOut]:
    docs, total, page, page_size = paginate_query(db.query(Document).order_by(Document.folder_id.asc(), Document.sort_order.asc(), Document.id.asc()), page, page_size)
    return page_payload([serialize_document(db, item) for item in docs], total, page, page_size)


@router.post("/documents", response_model=DocumentOut)
def admin_create_document(payload: DocumentCreate, db: Session = Depends(get_db)) -> DocumentOut:
    doc = Document(
        title=payload.title,
        content=payload.content,
        folder_id=payload.folder_id,
        author=payload.author,
        sort_order=payload.sort_order if payload.sort_order is not None else next_sort_order(db, Document, "folder_id", payload.folder_id),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return serialize_document(db, doc)


@router.put("/documents/{document_id}", response_model=DocumentOut)
def admin_update_document(document_id: int, payload: DocumentUpdate, db: Session = Depends(get_db)) -> DocumentOut:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    data = payload.model_dump(exclude_unset=True)
    sort_order_requested = "sort_order" in data and data["sort_order"] is not None
    if "sort_order" in data and data["sort_order"] is None:
        data.pop("sort_order")
    if "folder_id" in data and data["folder_id"] != doc.folder_id and not sort_order_requested:
        data["sort_order"] = next_sort_order(db, Document, "folder_id", data["folder_id"])
    for key, value in data.items():
        setattr(doc, key, value)
    db.commit()
    db.refresh(doc)
    return serialize_document(db, doc)


@router.delete("/documents/{document_id}")
def admin_delete_document(document_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    db.query(DocumentComment).filter(DocumentComment.document_id == document_id).update({DocumentComment.parent_id: None}, synchronize_session=False)
    db.query(DocumentComment).filter(DocumentComment.document_id == document_id).delete(synchronize_session=False)
    db.query(Like).filter(Like.target_type == LikeTarget.document.value, Like.target_id == document_id).delete(synchronize_session=False)
    db.delete(doc)
    db.commit()
    return {"message": "文档已删除"}


@router.get("/users", response_model=Page[UserOut])
def admin_list_users(
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[UserOut]:
    query = db.query(User)
    if keyword:
        query = query.filter(or_(User.nickname.like(f"%{keyword}%"), User.email.like(f"%{keyword}%"), User.phone.like(f"%{keyword}%")))
    items, total, page, page_size = paginate_query(query.order_by(User.created_at.desc()), page, page_size)
    return page_payload(items, total, page, page_size)


@router.post("/users/{user_id}/ban", response_model=UserOut)
def admin_ban_user(user_id: int, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if user.role == UserRole.admin.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能封禁管理员")
    user.is_banned = True
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/unban", response_model=UserOut)
def admin_unban_user(user_id: int, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    user.is_banned = False
    db.commit()
    db.refresh(user)
    return user


@router.get("/comments", response_model=Page[AdminCommentOut])
def admin_list_comments(
    target: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[AdminCommentOut]:
    task_query = (
        db.query(
            TaskComment.id.label("id"),
            literal("task").label("target"),
            TaskComment.task_id.label("target_id"),
            func.coalesce(User.nickname, TaskComment.github_author_login, "GitHub 用户").label("user"),
            TaskComment.content.label("content"),
            TaskComment.admin_reply.label("admin_reply"),
            TaskComment.created_at.label("created_at"),
        )
        .outerjoin(User, TaskComment.user_id == User.id)
        .filter(TaskComment.deleted_at.is_(None))
    )
    document_query = (
        db.query(
            DocumentComment.id.label("id"),
            literal("document").label("target"),
            DocumentComment.document_id.label("target_id"),
            User.nickname.label("user"),
            DocumentComment.content.label("content"),
            DocumentComment.admin_reply.label("admin_reply"),
            DocumentComment.created_at.label("created_at"),
        )
        .join(User, DocumentComment.user_id == User.id)
        .filter(DocumentComment.deleted_at.is_(None))
    )
    if target == "task":
        comments = task_query.subquery()
    elif target == "document":
        comments = document_query.subquery()
    else:
        comments = task_query.union_all(document_query).subquery()
    query = db.query(
        comments.c.id,
        comments.c.target,
        comments.c.target_id,
        comments.c.user,
        comments.c.content,
        comments.c.admin_reply,
        comments.c.created_at,
    ).order_by(desc(comments.c.created_at))
    rows, total, page, page_size = paginate_query(query, page, page_size)
    items = [AdminCommentOut(**dict(row._mapping)) for row in rows]
    return page_payload(items, total, page, page_size)


@router.post("/comments/{target}/{comment_id}/reply")
def admin_reply_comment(target: str, comment_id: int, payload: CommentAdminUpdate, db: Session = Depends(get_db)) -> dict[str, str]:
    comment = _get_comment(db, target, comment_id)
    comment.admin_reply = payload.admin_reply
    db.commit()
    return {"message": "回复已保存"}


@router.delete("/comments/{target}/{comment_id}")
def admin_delete_comment(
    target: str,
    comment_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    comment = _get_comment(db, target, comment_id)
    comment.deleted_at = datetime.now(timezone.utc)
    db.commit()
    if target == "task":
        background_tasks.add_task(delete_comment_from_github_background, comment.id)
    return {"message": "评论已删除"}


@router.get("/orders", response_model=Page[SponsorOrderOut])
def admin_list_orders(
    task_id: int | None = None,
    user_id: int | None = None,
    status_value: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[SponsorOrderOut]:
    query = db.query(SponsorOrder)
    if task_id:
        query = query.filter(SponsorOrder.task_id == task_id)
    if user_id:
        query = query.filter(SponsorOrder.user_id == user_id)
    if status_value:
        query = query.filter(SponsorOrder.status == status_value)
    items, total, page, page_size = paginate_query(query.order_by(SponsorOrder.created_at.desc()), page, page_size)
    return page_payload(items, total, page, page_size)


def _get_comment(db: Session, target: str, comment_id: int) -> TaskComment | DocumentComment:
    model = TaskComment if target == "task" else DocumentComment if target == "document" else None
    if model is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="评论类型错误")
    comment = db.get(model, comment_id)
    if not comment or comment.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
    return comment


def task_comment_author(item: TaskComment) -> str:
    if item.user:
        return item.user.nickname
    return item.github_author_login or "GitHub 用户"


def serialize_admin_task_comment(item: TaskComment) -> TaskCommentOut:
    return TaskCommentOut(
        id=item.id,
        task_id=item.task_id,
        user_id=item.user_id,
        user_nickname=task_comment_author(item),
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


def schedule_task_github_sync_after_admin_update(
    db: Session,
    background_tasks: BackgroundTasks,
    task: Task,
    previous_status: str,
    changed_fields: set[str],
) -> None:
    moved_out_of_review = (
        "status" in changed_fields
        and previous_status == TaskStatus.pending_review.value
        and task.status != TaskStatus.pending_review.value
    )
    if moved_out_of_review and task.source != TaskSource.github.value and task.github_issue_number is None:
        mark_task_github_sync_pending(db, task)
        background_tasks.add_task(sync_task_to_github_background, task.id, True)
        return
    if task.github_issue_number is None:
        return
    if changed_fields.intersection({"name", "description", "status"}):
        mark_task_github_sync_pending(db, task)
        background_tasks.add_task(sync_task_to_github_background, task.id, False)


def mark_task_github_sync_pending(db: Session, task: Task) -> None:
    task.github_sync_status = GitHubSyncStatus.pending.value
    task.github_sync_error = None
    db.commit()
    db.refresh(task)
