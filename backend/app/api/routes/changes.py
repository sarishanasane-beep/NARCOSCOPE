"""Change detection API (Prompt 2 Part 3)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.graph_change import GraphChange
from app.schemas.changes import ChangeList, ChangeOut, CompareRequest
from app.services.graph.changes import _change_out, compare_snapshots
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/changes", tags=["changes"])


@router.post("/compare")
def changes_compare(payload: CompareRequest, db: Session = Depends(get_db)) -> dict:
    """Compare two snapshots: persist + summarize detected changes."""
    return compare_snapshots(db, payload.previous_snapshot_id, payload.current_snapshot_id)


@router.get("", response_model=ChangeList)
def changes_list(
    category: str | None = None,
    significance: str | None = None,
    snapshot_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> ChangeList:
    query = db.query(GraphChange).order_by(GraphChange.created_at.desc())
    if category:
        query = query.filter(GraphChange.category == category)
    if significance:
        query = query.filter(GraphChange.significance == significance)
    if snapshot_id:
        query = query.filter(GraphChange.snapshot_id == snapshot_id)
    total = query.count()
    rows = query.offset(offset).limit(limit).all()
    return ChangeList(
        items=[ChangeOut.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/{change_id}", response_model=ChangeOut)
def changes_get(change_id: str, db: Session = Depends(get_db)) -> ChangeOut:
    row = db.get(GraphChange, change_id)
    if row is None:
        raise NotFoundError("Change not found.")
    return ChangeOut.model_validate(row)
