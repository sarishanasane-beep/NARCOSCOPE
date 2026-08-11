"""Investigation Priority API (Prompt 2 Part 3).

The score is an analytical signal (NOT guilt/criminality). Every response
includes the full 0-100 breakdown and the disclaimer.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.priority import PriorityOut
from app.services.graph.priority import priority_for_entity, priority_ranking

router = APIRouter(prefix="/priority", tags=["priority"])


@router.get("/ranking")
def priority_ranking_endpoint(limit: int = 50, db: Session = Depends(get_db)) -> dict:
    """Top-N ACTIVE entities by Investigation Priority (with breakdowns)."""
    items = priority_ranking(db, limit=limit)
    return {"total": len(items), "items": items}


@router.get("/{entity_id}", response_model=PriorityOut)
def priority_entity(
    entity_id: str, case_id: str | None = None, db: Session = Depends(get_db)
) -> PriorityOut:
    """Full Investigation Priority breakdown for one entity."""
    return PriorityOut(**priority_for_entity(db, entity_id, case_id=case_id))
