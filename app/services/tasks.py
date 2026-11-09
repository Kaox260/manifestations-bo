"""File de tâches en base : réservation atomique et reprise des tâches bloquées."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Task
from app.schemas import TaskStatus


def claim_next_task(db: Session, task_type: str | None = None) -> Task | None:
    """Réserve la plus ancienne tâche `pending` (-> `running`). Sûr avec plusieurs workers."""
    stmt = select(Task).where(Task.status == TaskStatus.pending).order_by(Task.created_at).limit(1)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
    task = db.scalars(stmt.with_for_update(skip_locked=True)).first()
    if task is None:
        return None
    task.status = TaskStatus.running
    db.commit()
    db.refresh(task)
    return task


def requeue_stale(db: Session, older_than: timedelta) -> int:
    """Remet en `pending` les tâches `running` inactives depuis `older_than` (worker mort)."""
    cutoff = datetime.now(timezone.utc) - older_than
    result = db.execute(
        update(Task)
        .where(Task.status == TaskStatus.running, Task.updated_at < cutoff)
        .values(status=TaskStatus.pending)
    )
    db.commit()
    return result.rowcount or 0
