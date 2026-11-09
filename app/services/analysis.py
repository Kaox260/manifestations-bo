"""Analyse d'une source : transcription + OCR -> Perplexity -> événement + tâche."""
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Event, Source, Task
from app.schemas import EventCreate, TaskStatus
from app.services import event_store, ocr, perplexity, whisper

logger = logging.getLogger(__name__)

TASK_TYPE = "analyze_source"


def _find_task(db: Session, source_id: uuid.UUID, task_id: uuid.UUID | None) -> Task | None:
    if task_id is not None:
        return db.get(Task, task_id)
    stmt = (
        select(Task)
        .where(Task.task_type == TASK_TYPE, Task.status == TaskStatus.running)
        .order_by(Task.created_at)
    )
    return next(
        (t for t in db.scalars(stmt) if (t.payload or {}).get("source_id") == str(source_id)), None
    )


def _gather_inputs(source: Source) -> tuple[str | None, str | None, list[str], dict[str, Any]]:
    """Transcription, OCR et commentaires, depuis le cache de raw_metadata ou les fichiers.

    Retourne aussi les entrées de cache nouvellement calculées (à persister).
    """
    meta = source.raw_metadata or {}
    fresh: dict[str, Any] = {}

    transcript = meta.get("transcript")
    if transcript is None:
        media = meta.get("audio_path") or meta.get("video_path")
        if media and Path(media).is_file():
            try:
                transcript = whisper.transcribe_audio(media)["text"] or None
                fresh["transcript"] = transcript
            except Exception:
                logger.exception("Transcription failed for source %s", source.id)

    ocr_text = meta.get("ocr_text")
    if ocr_text is None and source.screenshot_path and Path(source.screenshot_path).is_file():
        try:
            ocr_text = ocr.ocr_image(source.screenshot_path)
            fresh["ocr_text"] = ocr_text
        except Exception:
            logger.exception("OCR failed for source %s", source.id)

    comments = [str(c) for c in (meta.get("comments") or []) if c]
    return transcript, ocr_text, comments, fresh


def _upsert_event(db: Session, data: EventCreate) -> tuple[Event, str]:
    """Crée l'événement, ou met à jour l'existant s'il est encore `pending`.

    Un événement déjà validé/rejeté par un humain n'est jamais écrasé.
    Retourne (event, "created" | "updated" | "kept").
    """
    existing = db.scalars(
        select(Event)
        .where(
            Event.source_id == data.source_id,
            Event.event_type == data.event_type,
            Event.occurred_on == data.occurred_on,
            Event.city == data.city,
        )
        .order_by(Event.created_at)
    ).first()
    # needs_review reste True : un événement produit par un LLM exige toujours une relecture.
    if existing is None:
        return event_store.create_event(db, data, needs_review=True), "created"
    if existing.status != "pending":
        return existing, "kept"
    for key, value in event_store.event_values(data, needs_review=True).items():
        setattr(existing, key, value)
    event_store.link_sources(db, existing, data)
    return existing, "updated"


def _finish(db: Session, task: Task | None, *, error: str | None = None, result: dict | None = None):
    if task is None:
        return
    task.status = TaskStatus.failed if error else TaskStatus.done
    task.error = error
    task.result = result
    db.commit()


def analyze_source(
    source_id: uuid.UUID, task_id: uuid.UUID | None = None, db: Session | None = None
) -> Event | None:
    """Analyse la source et crée/met à jour l'événement. Met à jour la tâche associée.

    Sans `task_id`, la tâche `analyze_source` en cours pour cette source est utilisée.
    Retourne l'événement, ou None en cas d'échec (la tâche est alors `failed`).
    """
    own = db is None
    db = db or SessionLocal()
    task = None
    try:
        task = _find_task(db, source_id, task_id)
        source = db.get(Source, source_id)
        if source is None:
            _finish(db, task, error="source not found")
            return None

        transcript, ocr_text, comments, fresh = _gather_inputs(source)
        if fresh:
            source.raw_metadata = {**(source.raw_metadata or {}), **fresh}  # nouveau dict -> persisté
            db.commit()

        payload = perplexity.build_analysis_payload(source, transcript, ocr_text, comments)
        response = perplexity.call_perplexity(payload)
        data = perplexity.parse_perplexity_response(response, source_id=source.id)

        event, action = _upsert_event(db, data)
        _finish(
            db,
            task,
            result={
                "event_id": str(event.id),
                "action": action,
                "confidence": data.confidence,
                "model_needs_human_review": data.needs_human_review,
                "used_transcript": bool(transcript),
                "used_ocr": bool(ocr_text),
            },
        )
        db.refresh(event)
        return event
    except perplexity.PerplexityError as exc:
        db.rollback()
        logger.warning("Analysis of source %s failed: %s", source_id, type(exc).__name__)
        _finish(db, task, error=f"{type(exc).__name__}: {exc}"[:1000])
        return None
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected error analysing source %s", source_id)
        _finish(db, task, error=f"internal error: {type(exc).__name__}")
        return None
    finally:
        if own:
            db.close()
