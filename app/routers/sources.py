import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_token
from app.database import get_db
from app.models import Source
from app.schemas import SourceCreate, SourceResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post(
    "", response_model=SourceResponse, status_code=201, dependencies=[Depends(require_token)]
)
def create_source(data: SourceCreate, db: Session = Depends(get_db)):
    source = Source(**{**data.model_dump(), "url": str(data.url)})
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("", response_model=list[SourceResponse])
def list_sources(
    platform: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Source).order_by(Source.created_at.desc()).limit(limit).offset(offset)
    if platform:
        stmt = stmt.where(Source.platform == platform)
    return db.scalars(stmt).all()


@router.get("/{source_id}", response_model=SourceResponse)
def get_source(source_id: uuid.UUID, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source
