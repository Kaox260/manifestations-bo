"""Persistance des événements, partagée par l'API et le worker d'analyse."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, EventSource, Source
from app.schemas import EventCreate


def event_values(data: EventCreate, needs_review: bool | None = None) -> dict:
    values = data.model_dump(exclude={"needs_human_review", "publishable"})
    values["source_urls"] = [str(u) for u in data.source_urls]
    values["needs_review"] = data.needs_human_review if needs_review is None else needs_review
    return values


def link_sources(db: Session, event: Event, data: EventCreate) -> None:
    """Lie l'événement à sa source principale et aux sources connues citées dans source_urls."""
    wanted = {data.source_id}
    urls = [str(u) for u in data.source_urls]
    if urls:
        wanted.update(db.scalars(select(Source.id).where(Source.url.in_(urls))).all())
    existing = set(db.scalars(select(EventSource.source_id).where(EventSource.event_id == event.id)))
    db.add_all(EventSource(event_id=event.id, source_id=sid) for sid in wanted - existing)


def create_event(db: Session, data: EventCreate, needs_review: bool | None = None) -> Event:
    """Crée l'événement et ses liens (flush, pas de commit)."""
    event = Event(**event_values(data, needs_review))
    db.add(event)
    db.flush()
    link_sources(db, event, data)
    return event
