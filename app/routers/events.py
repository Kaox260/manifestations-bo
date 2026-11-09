import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event
from app.schemas import (
    EventCreate,
    EventRead,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONPoint,
)

router = APIRouter(prefix="/events", tags=["events"])


def _filtered(
    event_type: str | None, city: str | None, status: str | None,
    date_from: date | None, date_to: date | None,
):
    stmt = select(Event)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if city:
        stmt = stmt.where(Event.city == city)
    if status:
        stmt = stmt.where(Event.status == status)
    if date_from:
        stmt = stmt.where(Event.occurred_on >= date_from)
    if date_to:
        stmt = stmt.where(Event.occurred_on <= date_to)
    return stmt


@router.post("", response_model=EventRead, status_code=201)
def create_event(data: EventCreate, db: Session = Depends(get_db)):
    event = Event(**data.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.post("/bulk", response_model=list[EventRead], status_code=201)
def create_events_bulk(items: list[EventCreate], db: Session = Depends(get_db)):
    events = [Event(**i.model_dump()) for i in items]
    db.add_all(events)
    db.commit()
    return events


@router.get("", response_model=list[EventRead])
def list_events(
    event_type: str | None = None,
    city: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = _filtered(event_type, city, status, date_from, date_to)
    stmt = stmt.order_by(Event.occurred_on.desc().nulls_last()).limit(limit).offset(offset)
    return db.scalars(stmt).all()


@router.get("/geojson", response_model=GeoJSONFeatureCollection)
def events_geojson(
    event_type: str | None = None,
    city: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    stmt = _filtered(event_type, city, status, date_from, date_to).where(
        Event.latitude.is_not(None), Event.longitude.is_not(None)
    )
    features = [
        GeoJSONFeature(
            geometry=GeoJSONPoint(coordinates=(e.longitude, e.latitude)),
            properties={
                "id": str(e.id),
                "title": e.title,
                "event_type": e.event_type,
                "city": e.city,
                "occurred_on": e.occurred_on.isoformat() if e.occurred_on else None,
                "status": e.status,
                "participants_estimate": e.participants_estimate,
            },
        )
        for e in db.scalars(stmt).all()
    ]
    return GeoJSONFeatureCollection(features=features)


@router.get("/{event_id}", response_model=EventRead)
def get_event(event_id: uuid.UUID, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return event
