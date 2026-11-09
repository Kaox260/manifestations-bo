import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, model_validator


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
Platform = Literal["tiktok", "youtube", "web", "x", "facebook"]
Reliability = Literal["official", "press", "social", "unknown"]
ActorRole = Literal["police", "gendarmerie", "protester", "bystander", "journalist", "unknown"]


class SourceCreate(BaseModel):
    platform: Platform
    url: HttpUrl
    title: Optional[str] = None
    raw_text: Optional[str] = None
    published_at: Optional[datetime] = None
    screenshot_path: Optional[str] = None
    raw_metadata: Optional[dict] = None
    reliability: Reliability = "unknown"


# ---- Events ----
class EventCreate(BaseModel):
    source_id: uuid.UUID
    event_type: Literal[
        "police_violence_allegation",
        "police_injury",
        "protester_injury",
        "arrest",
        "property_damage",
        "use_of_force",
        "other",
    ]
    occurred_on: date
    city: str
    location_raw: Optional[str] = None
    description: str
    actors: List[ActorRole]
    victims: List[ActorRole]
    injury_level: Literal["none", "minor", "serious", "unknown"] = "unknown"
    legal_status: Literal["none", "complaint", "investigation", "prosecution", "unknown"] = "unknown"
    verification_status: Literal["official", "corroborated", "alleged", "unverified", "disputed"]
    confidence: int = Field(ge=0, le=5)
    source_urls: List[HttpUrl]
    needs_human_review: bool = True
    extracted_keywords: List[str] = Field(default_factory=list)
    # Coordonnees precises optionnelles ; sinon point approximatif base sur la ville.
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def check_confidence_vs_verification(self) -> "EventCreate":
        if self.verification_status == "official" and self.confidence < 4:
            raise ValueError("verification_status 'official' requires confidence >= 4")
        if self.verification_status == "unverified" and self.confidence > 2:
            raise ValueError("verification_status 'unverified' requires confidence <= 2")
        return self

    @computed_field
    @property
    def publishable(self) -> bool:
        """Un evenement a revoir par un humain n'est jamais publie par defaut."""
        return not self.needs_human_review


class SourceResponse(ORMModel):
    id: uuid.UUID
    platform: str
    url: str
    title: Optional[str] = None
    raw_text: Optional[str] = None
    published_at: Optional[datetime] = None
    screenshot_path: Optional[str] = None
    raw_metadata: Optional[dict] = None
    reliability: str
    created_at: datetime


class EventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[EventStatus] = None
    confidence: Optional[int] = Field(default=None, ge=0, le=5)
    needs_review: Optional[bool] = None
    description: Optional[str] = Field(default=None, min_length=1)
    location_raw: Optional[str] = None


class EventResponse(ORMModel):
    id: uuid.UUID
    occurred_on: date
    city: str
    location_raw: Optional[str] = None
    event_type: str
    description: str
    status: str
    confidence: int
    needs_review: bool
    created_at: datetime


# ---- GeoJSON ----
class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: dict


class GeoJSONResponse(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[GeoJSONFeature]


# ---- Tasks ----
class TaskCreate(BaseModel):
    task_type: str = Field(min_length=1, max_length=50)
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskResultUpdate(BaseModel):
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
