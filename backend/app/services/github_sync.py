from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import GitHubSyncEvent, GitHubSyncStatus, Task, TaskComment, TaskSource, TaskStatus
from app.services.task_ordering import normalize_task_sort_orders


STATUS_LABEL_PREFIX = "issue-wiki/status:"
STATUS_LABELS = {
    TaskStatus.pending_review.value: ("issue-wiki/status:pending-review", "f59e0b"),
    TaskStatus.pending_start.value: ("issue-wiki/status:pending-start", "2563eb"),
    TaskStatus.in_progress.value: ("issue-wiki/status:in-progress", "059669"),
    TaskStatus.completed.value: ("issue-wiki/status:completed", "6b7280"),
}
STATUS_BY_LABEL = {label: status for status, (label, _) in STATUS_LABELS.items()}


class GitHubSyncError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self) -> None:
        if not settings.github_repo:
            raise GitHubSyncError("GITHUB_PROJECT_URL 必须是 GitHub 仓库地址")
        if not settings.github_token:
            raise GitHubSyncError("GITHUB_TOKEN 未配置")
        self.repo = settings.github_repo
        self.base_url = settings.github_api_base_url.rstrip("/")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.request(method, url, headers=self.headers, timeout=20, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubSyncError(f"GitHub API 请求失败：{exc}") from exc
        if response.status_code >= 400:
            message = response.text
            try:
                data = response.json()
                message = data.get("message") or message
            except ValueError:
                pass
            raise GitHubSyncError(f"GitHub API {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()


def sync_enabled() -> bool:
    return bool(settings.github_sync_enabled)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def issue_author_login(issue: dict[str, Any]) -> str | None:
    user = issue.get("user") or {}
    return user.get("login")


def comment_author_login(comment: dict[str, Any]) -> str | None:
    user = comment.get("user") or {}
    return user.get("login")


def task_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, STATUS_LABELS[TaskStatus.pending_start.value])[0]


def apply_issue_mapping(task: Task, issue: dict[str, Any], repo: str) -> None:
    task.github_repo = repo
    task.github_issue_id = issue.get("id")
    task.github_issue_node_id = issue.get("node_id")
    task.github_issue_number = issue.get("number")
    task.github_issue_url = issue.get("html_url")
    task.github_author_login = issue_author_login(issue)
    task.github_state = issue.get("state")
    task.github_updated_at = parse_github_datetime(issue.get("updated_at"))
    task.last_github_sync_at = now_utc()
    task.github_sync_status = GitHubSyncStatus.synced.value
    task.github_sync_error = None


def status_from_github_issue(issue: dict[str, Any]) -> str:
    for item in issue.get("labels") or []:
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name in STATUS_BY_LABEL:
            return STATUS_BY_LABEL[name]
    return TaskStatus.completed.value if issue.get("state") == "closed" else TaskStatus.pending_review.value


def find_task_by_issue(db: Session, repo: str, issue: dict[str, Any]) -> Task | None:
    issue_id = issue.get("id")
    issue_number = issue.get("number")
    filters = []
    if issue_id is not None:
        filters.append(Task.github_issue_id == issue_id)
    if issue_number is not None:
        filters.append(and_(Task.github_repo == repo, Task.github_issue_number == issue_number))
    if not filters:
        return None
    return db.query(Task).filter(or_(*filters)).first()


def upsert_task_from_issue(db: Session, issue: dict[str, Any], repo: str | None = None) -> tuple[Task | None, bool]:
    if issue.get("pull_request"):
        return None, False
    repo_name = repo or settings.github_repo
    if not repo_name:
        raise GitHubSyncError("GITHUB_PROJECT_URL 必须是 GitHub 仓库地址")

    task = find_task_by_issue(db, repo_name, issue)
    previous_status = task.status if task is not None else None
    previous_sort_order = task.sort_order if task is not None else None
    created = False
    if task is None:
        task = Task(
            name=issue.get("title") or f"GitHub Issue #{issue.get('number')}",
            description=issue.get("body") or "",
            sort_order=0,
            start_amount=Decimal("0"),
            status=status_from_github_issue(issue),
            is_hidden=False,
            source=TaskSource.github.value,
        )
        db.add(task)
        created = True
    else:
        task.name = issue.get("title") or task.name
        task.description = issue.get("body") or ""
        if task.source == TaskSource.github.value:
            task.status = status_from_github_issue(issue)

    apply_issue_mapping(task, issue, repo_name)
    normalize_task_sort_orders(db, task, github_task_requested_sort_order(task, previous_status, previous_sort_order, created))
    db.commit()
    db.refresh(task)
    return task, created


def github_task_requested_sort_order(task: Task, previous_status: str | None, previous_sort_order: int | None, created: bool) -> int | None:
    if created or task.status == TaskStatus.completed.value or previous_status == TaskStatus.completed.value:
        return None
    return previous_sort_order


def ensure_status_label(client: GitHubClient, status: str) -> str:
    label, color = STATUS_LABELS.get(status, STATUS_LABELS[TaskStatus.pending_start.value])
    try:
        client.request(
            "POST",
            f"/repos/{client.repo}/labels",
            json={"name": label, "color": color, "description": "Issue Wiki task status"},
        )
    except GitHubSyncError as exc:
        if "422" not in str(exc):
            raise
    return label


def labels_with_status(client: GitHubClient, issue: dict[str, Any], status: str) -> list[str]:
    label = ensure_status_label(client, status)
    labels = []
    for item in issue.get("labels") or []:
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name and not name.startswith(STATUS_LABEL_PREFIX):
            labels.append(name)
    labels.append(label)
    return labels


def create_github_issue(client: GitHubClient, task: Task) -> dict[str, Any]:
    label = ensure_status_label(client, task.status)
    issue = client.request(
        "POST",
        f"/repos/{client.repo}/issues",
        json={"title": task.name, "body": task.description or "", "labels": [label]},
    )
    if task.status == TaskStatus.completed.value:
        issue = client.request("PATCH", f"/repos/{client.repo}/issues/{issue['number']}", json={"state": "closed"})
    return issue


def update_github_issue(client: GitHubClient, task: Task) -> dict[str, Any]:
    if task.github_issue_number is None:
        raise GitHubSyncError("任务未绑定 GitHub issue")
    current = client.request("GET", f"/repos/{client.repo}/issues/{task.github_issue_number}")
    payload = {
        "title": task.name,
        "body": task.description or "",
        "state": "closed" if task.status == TaskStatus.completed.value else "open",
        "labels": labels_with_status(client, current, task.status),
    }
    return client.request("PATCH", f"/repos/{client.repo}/issues/{task.github_issue_number}", json=payload)


def sync_task_to_github(db: Session, task: Task, create_if_missing: bool = False) -> bool:
    if not sync_enabled():
        task.github_sync_status = GitHubSyncStatus.pending.value
        db.commit()
        return False
    try:
        client = GitHubClient()
        if task.github_issue_number is None:
            if not create_if_missing:
                return False
            issue = create_github_issue(client, task)
        else:
            issue = update_github_issue(client, task)
        apply_issue_mapping(task, issue, client.repo)
        db.commit()
        db.refresh(task)
        return True
    except Exception as exc:
        task.github_sync_status = GitHubSyncStatus.error.value
        task.github_sync_error = str(exc)
        task.last_github_sync_at = now_utc()
        db.commit()
        return False


def apply_comment_mapping(comment: TaskComment, github_comment: dict[str, Any]) -> None:
    comment.github_comment_id = github_comment.get("id")
    comment.github_author_login = comment_author_login(github_comment)
    comment.github_updated_at = parse_github_datetime(github_comment.get("updated_at"))
    comment.last_github_sync_at = now_utc()
    comment.github_sync_error = None


def upsert_comment_from_github(db: Session, task: Task, github_comment: dict[str, Any], deleted: bool = False) -> tuple[TaskComment | None, bool]:
    comment_id = github_comment.get("id")
    if comment_id is None:
        return None, False
    comment = db.query(TaskComment).filter(TaskComment.github_comment_id == comment_id).first()
    if comment is None and deleted:
        return None, False

    created = False
    if comment is None:
        comment = TaskComment(
            task_id=task.id,
            user_id=None,
            content=github_comment.get("body") or "",
            github_author_login=comment_author_login(github_comment),
        )
        db.add(comment)
        created = True
    else:
        comment.task_id = task.id
        comment.content = github_comment.get("body") or ""
        comment.deleted_at = None

    apply_comment_mapping(comment, github_comment)
    if deleted:
        comment.deleted_at = now_utc()
    db.commit()
    db.refresh(comment)
    return comment, created


def sync_comment_to_github(db: Session, comment: TaskComment) -> bool:
    if not sync_enabled() or comment.github_author_login:
        return False
    task = comment.task
    if task.github_issue_number is None:
        return False
    try:
        client = GitHubClient()
        if comment.github_comment_id is None:
            result = client.request(
                "POST",
                f"/repos/{client.repo}/issues/{task.github_issue_number}/comments",
                json={"body": comment.content},
            )
        else:
            result = client.request(
                "PATCH",
                f"/repos/{client.repo}/issues/comments/{comment.github_comment_id}",
                json={"body": comment.content},
            )
        apply_comment_mapping(comment, result)
        db.commit()
        db.refresh(comment)
        return True
    except Exception as exc:
        comment.github_sync_error = str(exc)
        comment.last_github_sync_at = now_utc()
        db.commit()
        return False


def delete_comment_from_github(db: Session, comment: TaskComment) -> bool:
    if not sync_enabled() or comment.github_comment_id is None:
        return False
    try:
        client = GitHubClient()
        client.request("DELETE", f"/repos/{client.repo}/issues/comments/{comment.github_comment_id}")
        comment.github_sync_error = None
        comment.last_github_sync_at = now_utc()
        db.commit()
        return True
    except Exception as exc:
        comment.github_sync_error = str(exc)
        comment.last_github_sync_at = now_utc()
        db.commit()
        return False


def sync_task_to_github_background(task_id: int, create_if_missing: bool = False) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return
        sync_task_to_github(db, task, create_if_missing=create_if_missing)
    except Exception as exc:
        db.rollback()
        task = db.get(Task, task_id)
        if task is not None:
            task.github_sync_status = GitHubSyncStatus.error.value
            task.github_sync_error = str(exc)
            task.last_github_sync_at = now_utc()
            db.commit()
    finally:
        db.close()


def sync_comment_to_github_background(comment_id: int) -> None:
    db = SessionLocal()
    try:
        comment = db.get(TaskComment, comment_id)
        if comment is None or comment.deleted_at is not None:
            return
        sync_comment_to_github(db, comment)
    except Exception as exc:
        db.rollback()
        comment = db.get(TaskComment, comment_id)
        if comment is not None:
            comment.github_sync_error = str(exc)
            comment.last_github_sync_at = now_utc()
            db.commit()
    finally:
        db.close()


def delete_comment_from_github_background(comment_id: int) -> None:
    db = SessionLocal()
    try:
        comment = db.get(TaskComment, comment_id)
        if comment is None:
            return
        delete_comment_from_github(db, comment)
    except Exception as exc:
        db.rollback()
        comment = db.get(TaskComment, comment_id)
        if comment is not None:
            comment.github_sync_error = str(exc)
            comment.last_github_sync_at = now_utc()
            db.commit()
    finally:
        db.close()


def sync_issue_comments_from_github(db: Session, task: Task, client: GitHubClient) -> int:
    if task.github_issue_number is None:
        return 0
    imported = 0
    page = 1
    while True:
        comments = client.request(
            "GET",
            f"/repos/{client.repo}/issues/{task.github_issue_number}/comments",
            params={"per_page": 100, "page": page},
        )
        if not comments:
            break
        for github_comment in comments:
            _, created = upsert_comment_from_github(db, task, github_comment)
            if created:
                imported += 1
        if len(comments) < 100:
            break
        page += 1
    return imported


def sync_historical_issues(db: Session) -> dict[str, Any]:
    if not sync_enabled():
        raise GitHubSyncError("GitHub 同步未启用")
    client = GitHubClient()
    result: dict[str, Any] = {"imported": 0, "skipped": 0, "failed": 0, "comments_imported": 0, "errors": []}
    page = 1
    while True:
        issues = client.request(
            "GET",
            f"/repos/{client.repo}/issues",
            params={"state": "all", "sort": "created", "direction": "asc", "per_page": 100, "page": page},
        )
        if not issues:
            break
        for issue in issues:
            if issue.get("pull_request"):
                result["skipped"] += 1
                continue
            try:
                existed = find_task_by_issue(db, client.repo, issue) is not None
                task, created = upsert_task_from_issue(db, issue, client.repo)
                if task is None:
                    result["skipped"] += 1
                    continue
                if created and not existed:
                    result["imported"] += 1
                else:
                    result["skipped"] += 1
                result["comments_imported"] += sync_issue_comments_from_github(db, task, client)
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append(f"#{issue.get('number')}: {exc}")
        if len(issues) < 100:
            break
        page += 1
    return result


def start_sync_event(db: Session, delivery_id: str | None, event_type: str, action: str | None) -> tuple[GitHubSyncEvent, bool]:
    if delivery_id:
        existing = db.query(GitHubSyncEvent).filter(GitHubSyncEvent.delivery_id == delivery_id).first()
        if existing:
            return existing, False
    item = GitHubSyncEvent(
        delivery_id=delivery_id,
        event_type=event_type,
        action=action,
        direction="github_to_local",
        status="processing",
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(GitHubSyncEvent).filter(GitHubSyncEvent.delivery_id == delivery_id).first()
        if existing:
            return existing, False
        raise
    db.refresh(item)
    return item, True


def finish_sync_event(
    db: Session,
    item: GitHubSyncEvent,
    status: str,
    target_type: str | None = None,
    target_id: int | None = None,
    error: str | None = None,
) -> None:
    item.status = status
    item.target_type = target_type
    item.target_id = target_id
    item.error = error
    db.commit()


def process_github_webhook(db: Session, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    repo = payload.get("repository", {}).get("full_name") or settings.github_repo
    if repo != settings.github_repo:
        return {"status": "ignored", "message": "仓库不匹配"}

    if event_type == "issues":
        issue = payload.get("issue") or {}
        if issue.get("pull_request"):
            return {"status": "ignored", "message": "PR 已过滤"}
        if action not in {"opened", "edited", "reopened", "closed", "labeled", "unlabeled"}:
            return {"status": "ignored", "message": f"未处理的 issue action: {action}"}
        task, created = upsert_task_from_issue(db, issue, repo)
        return {"status": "created" if created else "updated", "target_type": "task", "target_id": task.id if task else None}

    if event_type == "issue_comment":
        issue = payload.get("issue") or {}
        if issue.get("pull_request"):
            return {"status": "ignored", "message": "PR 评论已过滤"}
        github_comment = payload.get("comment") or {}
        task = find_task_by_issue(db, repo, issue)
        if task is None and action != "deleted":
            task, _ = upsert_task_from_issue(db, issue, repo)
        if task is None:
            return {"status": "ignored", "message": "未找到对应任务"}
        comment, created = upsert_comment_from_github(db, task, github_comment, deleted=action == "deleted")
        return {
            "status": "created" if created else "updated",
            "target_type": "task_comment",
            "target_id": comment.id if comment else None,
        }

    return {"status": "ignored", "message": f"未处理的事件类型: {event_type}"}
