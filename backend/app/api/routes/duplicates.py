from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.entities.duplicates import (
    detect_duplicates,
    duplicate_summary,
    keep_separate,
    merge_cases,
    merge_entities,
    reconcile_case_entity,
)

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


class MergeRequest(BaseModel):
    canonical_id: str
    duplicate_id: str
    reviewed_by: str | None = None
    reason: str | None = None


class KeepSeparateRequest(BaseModel):
    kind: str
    record_a_id: str
    record_b_id: str
    reviewed_by: str | None = None
    reason: str | None = None


@router.get("")
def list_duplicates(kind: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Possible-duplicate groups for human review.

    ``kind``: entity | case | case_entity (CASE-typed entity that mirrors
    an actual Case) | None (all).
    """
    return {
        "groups": detect_duplicates(db, kind=kind),
        "summary": duplicate_summary(db),
    }


class ReconcileCaseEntityRequest(BaseModel):
    entity_id: str
    case_id: str
    reviewed_by: str | None = None
    reason: str | None = None


@router.post("/case-entity/reconcile")
def reconcile_case_entity_pair(
    payload: ReconcileCaseEntityRequest, db: Session = Depends(get_db)
) -> dict:
    """Reconcile a CASE-typed Entity into its canonical Case.

    Explicit human action: marks the entity MERGED (never an independent
    record again), preserves every relationship and its provenance; the
    graph keeps routing edges to the single canonical CASE node.
    """
    result = reconcile_case_entity(
        db, payload.entity_id, payload.case_id,
        user=payload.reviewed_by, note=payload.reason,
    )
    db.commit()
    return result


@router.get("/summary")
def duplicates_summary(db: Session = Depends(get_db)) -> dict:
    """Data-quality counts (total / possible / confirmed / merged)."""
    return duplicate_summary(db)


@router.post("/entities/merge")
def merge_entity_pair(payload: MergeRequest, db: Session = Depends(get_db)) -> dict:
    """Merge two entities after explicit human approval (references repointed)."""
    result = merge_entities(
        db, payload.canonical_id, payload.duplicate_id,
        user=payload.reviewed_by, note=payload.reason,
    )
    db.commit()
    return result


@router.post("/cases/merge")
def merge_case_pair(payload: MergeRequest, db: Session = Depends(get_db)) -> dict:
    """Merge two cases after explicit human approval (references repointed)."""
    result = merge_cases(
        db, payload.canonical_id, payload.duplicate_id,
        user=payload.reviewed_by, note=payload.reason,
    )
    db.commit()
    return result


@router.post("/keep-separate")
def keep_pair_separate(payload: KeepSeparateRequest, db: Session = Depends(get_db)) -> dict:
    """Record an explicit CONFIRMED DISTINCT decision (no repeated flagging)."""
    result = keep_separate(
        db, payload.kind, payload.record_a_id, payload.record_b_id,
        user=payload.reviewed_by, note=payload.reason,
    )
    db.commit()
    return result
