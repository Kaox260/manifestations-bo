"""Worker : consomme la file `tasks` en base.

    python -m app.worker run                 # boucle (service systemd)
    python -m app.worker once                # traite les tâches en attente puis s'arrête
    python -m app.worker enqueue-tiktok [q]  # planifie une découverte (q ou TIKTOK_QUERIES)

Types de tâches : `analyze_source` {source_id}, `discover_tiktok` {query, max_scroll?}.
"""
import argparse
import logging
import signal
import time
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Task
from app.schemas import TaskStatus
from app.services import analysis, tiktok
from app.services.tasks import claim_next_task, requeue_stale

logger = logging.getLogger("worker")

IDLE_SLEEP_SECONDS = 5
STALE_AFTER = timedelta(minutes=30)
_stop = False


def _request_stop(signum, frame):
    global _stop
    _stop = True
    logger.info("Signal %s reçu : arrêt après la tâche en cours", signum)


def _finish(db: Session, task: Task, *, result: dict | None = None, error: str | None = None):
    task.status = TaskStatus.failed if error else TaskStatus.done
    task.result, task.error = result, error
    db.commit()


def process_task(db: Session, task: Task) -> None:
    """Exécute une tâche réservée. Ne lève jamais : l'issue est écrite dans la tâche."""
    payload = task.payload or {}
    try:
        if task.task_type == "analyze_source":
            try:
                source_id = uuid.UUID(str(payload.get("source_id")))
            except ValueError:
                return _finish(db, task, error="invalid source_id")
            # analyze_source met lui-même la tâche à jour (done / failed).
            analysis.analyze_source(source_id, task_id=task.id, db=db)
        elif task.task_type == "discover_tiktok":
            query = (payload.get("query") or "").strip()
            if not query:
                return _finish(db, task, error="missing query")
            stats = tiktok.run_tiktok_discovery(query, int(payload.get("max_scroll", tiktok.MAX_SCROLL)))
            _finish(db, task, result=stats)
        else:
            _finish(db, task, error=f"unknown task_type {task.task_type!r}")
    except Exception as exc:
        db.rollback()
        logger.exception("Task %s crashed", task.id)
        _finish(db, task, error=f"internal error: {type(exc).__name__}")


def run_once() -> int:
    """Traite toutes les tâches en attente ; retourne leur nombre."""
    n = 0
    with SessionLocal() as db:
        while not _stop and (task := claim_next_task(db)) is not None:
            logger.info("Task %s (%s)", task.id, task.task_type)
            process_task(db, task)
            n += 1
    return n


def run_forever() -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    logger.info("Worker démarré")
    while not _stop:
        try:
            with SessionLocal() as db:
                if requeue := requeue_stale(db, STALE_AFTER):
                    logger.warning("%d tâche(s) bloquée(s) remise(s) en file", requeue)
            if run_once() == 0:
                time.sleep(IDLE_SLEEP_SECONDS)
        except Exception:
            logger.exception("Erreur de boucle (base indisponible ?)")
            time.sleep(IDLE_SLEEP_SECONDS * 3)
    logger.info("Worker arrêté")


def enqueue_tiktok(queries: list[str], db: Session | None = None) -> int:
    """Crée une tâche de découverte par requête, sans doublon pending/running."""
    own = db is None
    db = db or SessionLocal()
    created = 0
    try:
        open_tasks = db.scalars(
            select(Task).where(
                Task.task_type == "discover_tiktok",
                Task.status.in_([TaskStatus.pending, TaskStatus.running]),
            )
        ).all()
        busy = {(t.payload or {}).get("query") for t in open_tasks}
        for q in queries:
            if q and q not in busy:
                db.add(Task(task_type="discover_tiktok", payload={"query": q}))
                created += 1
        db.commit()
    finally:
        if own:
            db.close()
    return created


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="app.worker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("once")
    enq = sub.add_parser("enqueue-tiktok")
    enq.add_argument("query", nargs="*")
    args = parser.parse_args(argv)

    if args.cmd == "run":
        run_forever()
    elif args.cmd == "once":
        logger.info("%d tâche(s) traitée(s)", run_once())
    else:
        queries = [" ".join(args.query)] if args.query else settings.tiktok_queries
        if not queries:
            logger.error("Aucune requête : passez-en une ou définissez TIKTOK_QUERIES")
            return 1
        logger.info("%d tâche(s) de découverte créée(s)", enqueue_tiktok(queries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
