"""Cross-case intelligence API (Prompt 2 Part 2/3)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.graph.cross_case import case_overlap, cross_case_connections

router = APIRouter(prefix="/cross-case", tags=["cross-case"])


@router.get("/entity/{entity_id}")
def cross_case_entity(entity_id: str, db: Session = Depends(get_db)) -> dict:
    """Cross-case connections for one canonical entity (never one node per
    case)."""
    return cross_case_connections(db, entity_id)


@router.get("/overlap")
def cross_case_overlap(db: Session = Depends(get_db)) -> dict:
    """Case overlap detection: trusted entities/events connecting cases,
    with evidence references."""
    overlaps = case_overlap(db)
    return {"total": len(overlaps), "overlaps": overlaps}
