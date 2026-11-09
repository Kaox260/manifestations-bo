import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import worker
from app.models import Task
from app.services import analysis, tiktok
from app.services.tasks import claim_next_task, requeue_stale


def add_task(db, task_type, payload=None, status="pending"):
    t = Task(task_type=task_type, payload=payload or {}, status=status)
    db.add(t); db.commit()
    return t


def test_claim_and_requeue(db):
    t = add_task(db, "x")
    assert claim_next_task(db).id == t.id and t.status == "running"
    assert claim_next_task(db) is None
    t.updated_at = datetime.now(timezone.utc) - timedelta(hours=2); db.commit()
    assert requeue_stale(db, timedelta(minutes=30)) == 1
    db.refresh(t)
    assert t.status == "pending"


def test_process_analyze_dispatch(db, monkeypatch):
    sid = uuid.uuid4()
    calls = []
    monkeypatch.setattr(analysis, "analyze_source", lambda s, task_id, db: calls.append((s, task_id)))
    t = add_task(db, "analyze_source", {"source_id": str(sid)}, "running")
    worker.process_task(db, t)
    assert calls == [(sid, t.id)]

    bad = add_task(db, "analyze_source", {"source_id": "nope"}, "running")
    worker.process_task(db, bad)
    assert bad.status == "failed" and bad.error == "invalid source_id"


def test_process_discovery_and_unknown(db, monkeypatch):
    monkeypatch.setattr(tiktok, "run_tiktok_discovery", lambda q, n: {"found": 3, "q": q})
    t = add_task(db, "discover_tiktok", {"query": "manif"}, "running")
    worker.process_task(db, t)
    assert t.status == "done" and t.result == {"found": 3, "q": "manif"}

    nq = add_task(db, "discover_tiktok", {}, "running")
    worker.process_task(db, nq)
    assert nq.status == "failed"

    unk = add_task(db, "???", None, "running")
    worker.process_task(db, unk)
    assert unk.status == "failed" and "unknown" in unk.error


def test_process_task_never_raises(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(tiktok, "run_tiktok_discovery", boom)
    t = add_task(db, "discover_tiktok", {"query": "q"}, "running")
    worker.process_task(db, t)
    assert t.status == "failed" and t.error == "internal error: RuntimeError"


def test_enqueue_dedup(db):
    assert worker.enqueue_tiktok(["a", "b"], db=db) == 2
    assert worker.enqueue_tiktok(["a", "c"], db=db) == 1
    assert len(db.scalars(select(Task)).all()) == 3
