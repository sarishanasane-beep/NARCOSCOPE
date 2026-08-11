"""Global search API (Prompt 1 + Prompt 2 Part 2).

``GET /search`` is the original endpoint, now extended with optional
structured filters (entity type, event type, location, case number,
relationship type, source type, claim status, date range). Without any
filter it behaves exactly as before — backward compatible.

``POST /search/query`` runs the same ONE reusable query engine with a
structured body (used by saved-search re-runs and advanced filtering).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.annotations import InvestigationQueryIn
from app.services.search.query import InvestigationQuery, run_query
from app.services.search.service import search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search_all(
    q: str = "",
    limit: int = 20,
    entity_type: str | None = None,
    event_type: str | None = None,
    location: str | None = None,
    case_number: str | None = None,
    relationship_type: str | None = None,
    source_type: str | None = None,
    claim_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return search(
        db,
        q,
        limit=limit,
        entity_type=entity_type,
        event_type=event_type,
        location=location,
        case_number=case_number,
        relationship_type=relationship_type,
        source_type=source_type,
        claim_status=claim_status,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/query")
def search_query(payload: InvestigationQueryIn, db: Session = Depends(get_db)) -> dict:
    """Structured investigation query (same engine as saved searches)."""
    return run_query(db, InvestigationQuery(**payload.model_dump()))
