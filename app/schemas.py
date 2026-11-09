import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventStatus(StrEnum):
    pending = "pending"
    validated = "validated"
    rejected = "rejected"


class TaskStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Sources ----
class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=50)
    url: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class SourceRead(ORMModel, SourceCreate):
    id: uuid.UUID
    created_at: datetime


# ---- Events ----
class EventCreate(BaseModel):
    source_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    event_type: str = Field(min_length=1, max_length=50)
    city: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    occurred_on: date | None = None
    status: EventStatus = EventStatus.pending
    participants_estimate: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class EventRead(ORMModel, EventCreate):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---- GeoJSON ----
class GeoJSONPoint(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]  # [longitude, latitude]


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONPoint
    properties: dict[str, Any]


class GeoJSONFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]


# ---- Tasks ----
class TaskCreate(BaseModel):
    task_type: str = Field(min_length=1, max_length=50)
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class TaskRead(ORMModel):
    id: uuid.UUID
    task_type: str
    status: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
