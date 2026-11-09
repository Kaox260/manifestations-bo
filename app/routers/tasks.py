import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import require_token
from app.database import get_db
from app.models import Task
from app.schemas import TaskCreate, TaskRead, TaskResultUpdate, TaskStatus
from app.services.tasks import claim_next_task

# Toutes les routes de tâches exigent le token Bearer.
router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_token)])


@router.post("", response_model=TaskRead, status_code=201)
def create_task(data: TaskCreate, db: Session = Depends(get_db)):
    task = Task(**data.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# Déclarée avant /{task_id} pour que "next" ne soit pas interprété comme un UUID.
@router.get("/next", response_model=TaskRead, responses={204: {"description": "No pending task"}})
def next_task(db: Session = Depends(get_db)):
    """Réserve la plus ancienne tâche `pending` et la passe en `running`."""
    task = claim_next_task(db)
    return task if task is not None else Response(status_code=204)


@router.patch("/{task_id}/result", response_model=TaskRead)
def submit_task_result(task_id: uuid.UUID, data: TaskResultUpdate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != TaskStatus.running:
        raise HTTPException(409, f"Task is {task.status}, expected running")
    task.result = data.result
    task.error = data.error
    task.status = TaskStatus.failed if data.error else TaskStatus.done
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task
