"""Trusted graph snapshot API (Prompt 2 Part 3)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.graph_change import GraphChange
from app.models.graph_snapshot import GraphSnapshot
from app.schemas.changes import ChangeList
from app.schemas.snapshots import SnapshotCreate, SnapshotList, SnapshotOut
from app.services.graph.changes import _change_out
from app.services.graph.snapshots import create_snapshot, get_snapshot, list_snapshots
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.get("", response_model=SnapshotList)
def snapshots_list(db: Session = Depends(get_db)) -> SnapshotList:
    items = list_snapshots(db)
    return SnapshotList(items=[SnapshotOut.model_validate(s) for s in items], total=len(items))


@router.post("", response_model=SnapshotOut, status_code=201)
def snapshots_create(payload: SnapshotCreate, db: Session = Depends(get_db)) -> SnapshotOut:
    snapshot = create_snapshot(
        db, label=payload.label, created_by=payload.created_by
    )
    return SnapshotOut.model_validate(snapshot)


@router.get("/{snapshot_id}", response_model=SnapshotOut)
def snapshots_get(snapshot_id: str, db: Session = Depends(get_db)) -> SnapshotOut:
    snapshot = get_snapshot(db, snapshot_id)
    return SnapshotOut.model_validate(snapshot)


@router.get("/{snapshot_id}/changes", response_model=ChangeList)
def snapshots_changes(snapshot_id: str, db: Session = Depends(get_db)) -> ChangeList:
    """Persisted changes detected for this snapshot (if compared)."""
    if db.get(GraphSnapshot, snapshot_id) is None:
        raise NotFoundError("Snapshot not found.")
    rows = (
        db.query(GraphChange)
        .filter(GraphChange.snapshot_id == snapshot_id)
        .order_by(GraphChange.created_at)
        .all()
    )
    return ChangeList(items=[_change_out(r) for r in rows], total=len(rows))
