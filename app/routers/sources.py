import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Source
from app.schemas import SourceCreate, SourceRead

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("", response_model=SourceRead, status_code=201)
def create_source(data: SourceCreate, db: Session = Depends(get_db)):
    source = Source(**data.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("", response_model=list[SourceRead])
def list_sources(source_type: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Source).order_by(Source.created_at.desc())
    if source_type:
        stmt = stmt.where(Source.source_type == source_type)
    return db.scalars(stmt).all()


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: uuid.UUID, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source
