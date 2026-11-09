import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_token
from app.database import get_db
from app.geo import city_centroid
from app.models import Event, EventSource, Source
from app.services.event_store import create_event as create_event_record
from app.schemas import (
    EventCreate,
    EventResponse,
    EventStatus,
    EventUpdate,
    GeoJSONFeature,
    GeoJSONResponse,
)

router = APIRouter(prefix="/events", tags=["events"])

MIN_PUBLIC_CONFIDENCE = 3


@router.post(
    "", response_model=EventResponse, status_code=201, dependencies=[Depends(require_token)]
)
def create_event(data: EventCreate, db: Session = Depends(get_db)):
    if db.get(Source, data.source_id) is None:
        raise HTTPException(422, "source_id does not exist")

    event = create_event_record(db, data)

    db.commit()
    db.refresh(event)
    return event


@router.get("", response_model=list[EventResponse])
def list_events(
    city: str | None = None,
    event_type: str | None = None,
    status: EventStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_confidence: int | None = Query(None, ge=0, le=5),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Event)
    if city:
        stmt = stmt.where(Event.city == city)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if status:
        stmt = stmt.where(Event.status == status.value)
    if date_from:
        stmt = stmt.where(Event.occurred_on >= date_from)
    if date_to:
        stmt = stmt.where(Event.occurred_on <= date_to)
    if min_confidence is not None:
        stmt = stmt.where(Event.confidence >= min_confidence)
    stmt = stmt.order_by(Event.occurred_on.desc(), Event.created_at.desc())
    return db.scalars(stmt.limit(limit).offset(offset)).all()


# Chemin "/events.geojson" (prefix "/events" + ".geojson").
@router.get(".geojson", response_model=GeoJSONResponse)
def events_geojson(db: Session = Depends(get_db)):
    """Événements publiables : needs_review = false et confidence >= 3."""
    stmt = select(Event).where(
        Event.needs_review.is_(False), Event.confidence >= MIN_PUBLIC_CONFIDENCE
    )
    events = db.scalars(stmt).all()
    counts = dict(
        db.execute(
            select(EventSource.event_id, func.count())
            .where(EventSource.event_id.in_([e.id for e in events]))
            .group_by(EventSource.event_id)
        ).all()
    )
    features: list[GeoJSONFeature] = []
    for e in events:
        if e.latitude is not None and e.longitude is not None:
            lat, lon, precision = e.latitude, e.longitude, "exact"
        else:
            centroid = city_centroid(e.city)
            if centroid is None:
                continue  # ville inconnue : impossible de placer l'événement
            (lat, lon), precision = centroid, "city"
        features.append(
            GeoJSONFeature(
                geometry={"type": "Point", "coordinates": [lon, lat]},
                properties={
                    "id": str(e.id),
                    "event_type": e.event_type,
                    "occurred_on": e.occurred_on.isoformat(),
                    "city": e.city,
                    "location_raw": e.location_raw,
                    "description": e.description,
                    "status": e.status,
                    "verification_status": e.verification_status,
                    "confidence": e.confidence,
                    "sources_count": counts.get(e.id, 0),
                    "geo_precision": precision,
                },
            )
        )
    return GeoJSONResponse(features=features)


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: uuid.UUID, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return event


@router.patch(
    "/{event_id}", response_model=EventResponse, dependencies=[Depends(require_token)]
)
def update_event(event_id: uuid.UUID, data: EventUpdate, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    changes = data.model_dump(exclude_unset=True, mode="json")
    if "confidence" in changes and changes["confidence"] is None:
        raise HTTPException(422, "confidence cannot be null")
    for field in ("status", "needs_review", "description"):
        if field in changes and changes[field] is None:
            raise HTTPException(422, f"{field} cannot be null")

    new_conf = changes.get("confidence", event.confidence)
    if event.verification_status == "official" and new_conf < 4:
        raise HTTPException(422, "official events require confidence >= 4")
    if event.verification_status == "unverified" and new_conf > 2:
        raise HTTPException(422, "unverified events require confidence <= 2")

    for key, value in changes.items():
        setattr(event, key, value)
    db.commit()
    db.refresh(event)
    return event
