"""Timeline API (Prompt 2 Part 2)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.search.timeline import case_timeline, global_timeline
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("/global")
def timeline_global(
    event_type: str | None = None,
    location: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Chronological trusted timeline (event dates separate from
    publication dates; precision preserved)."""
    items = global_timeline(
        db,
        event_type=event_type,
        location=location,
        date_from=date_from,
        date_to=date_to,
    )
    return {"total": len(items), "items": items}


@router.get("/case/{case_id}")
def timeline_case(case_id: str, db: Session = Depends(get_db)) -> dict:
    """Chronological events of one case, clearly separating event date and
    source publication date."""
    try:
        items = case_timeline(db, case_id)
    except NotFoundError:
        raise
    return {"case_id": case_id, "total": len(items), "items": items}
