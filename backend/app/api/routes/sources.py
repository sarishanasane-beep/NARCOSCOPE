from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.sources import SourceList, SourceOut
from app.services.sources.service import get_source, list_sources

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=SourceList)
def list_all_sources(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)) -> SourceList:
    items = list_sources(db, limit=limit, offset=offset)
    return SourceList(items=[SourceOut.model_validate(s) for s in items], total=len(items))


@router.get("/{source_id}", response_model=SourceOut)
def get_one_source(source_id: str, db: Session = Depends(get_db)) -> SourceOut:
    return SourceOut.model_validate(get_source(db, source_id))
