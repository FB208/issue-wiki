from sqlalchemy.orm import Session

from app.models import Task, TaskStatus


def normalize_task_sort_orders(db: Session, target_task: Task | None = None, requested_sort_order: int | None = None) -> None:
    db.flush()
    target_id = target_task.id if target_task is not None else None

    completed_tasks = db.query(Task).filter(Task.status == TaskStatus.completed.value).all()
    for task in completed_tasks:
        task.sort_order = 0

    query = db.query(Task).filter(Task.status != TaskStatus.completed.value)
    if target_id is not None:
        query = query.filter(Task.id != target_id)
    active_tasks = query.order_by(Task.sort_order.asc(), Task.id.asc()).all()

    if target_task is not None:
        if target_task.status == TaskStatus.completed.value:
            target_task.sort_order = 0
        else:
            position = requested_position(requested_sort_order, len(active_tasks))
            active_tasks.insert(position - 1, target_task)

    for index, task in enumerate(active_tasks, start=1):
        task.sort_order = index


def requested_position(value: int | None, active_count: int) -> int:
    if value is None:
        return active_count + 1
    return min(max(int(value), 1), active_count + 1)
