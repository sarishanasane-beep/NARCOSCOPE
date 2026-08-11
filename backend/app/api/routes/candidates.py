from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.evidence import Evidence
from app.schemas.candidates import (
    CandidateConfirmRequest,
    CandidateList,
    CandidateOut,
    CandidateRejectRequest,
    CandidateUpdateRequest,
)
from app.services.candidates.service import (
    get_candidate,
    list_candidates,
    reject_candidate,
    update_candidate,
)
from app.services.validation.workflow import confirm_candidate
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/candidates", tags=["candidates"])

CONFIDENCE_MEANING = (
    "Confidence represents how strongly the system supports this extraction or match "
    "based on deterministic rules and available evidence. It is not a probability of guilt."
)


def _candidate_out(db: Session, candidate) -> CandidateOut:
    from app.schemas.evidence import EvidenceOut

    data = {
        "candidate_id": candidate.candidate_id,
        "candidate_type": candidate.candidate_type,
        "proposed_data": candidate.proposed_data or {},
        "source_document_id": candidate.source_document_id,
        "evidence_id": candidate.evidence_id,
        "confidence": candidate.confidence,
        "confidence_meaning": CONFIDENCE_MEANING if candidate.confidence is not None else None,
        "reason": candidate.reason,
        "status": candidate.status,
        "created_at": candidate.created_at,
        "reviewed_at": candidate.reviewed_at,
        "reviewed_by": candidate.reviewed_by,
    }
    if candidate.evidence_id:
        evidence = db.get(Evidence, candidate.evidence_id)
        if evidence:
            data["evidence"] = EvidenceOut.model_validate(evidence)

    # Every evidence occurrence for this candidate (primary + merged refs).
    ref_ids = [candidate.evidence_id] + list((candidate.proposed_data or {}).get("evidence_refs") or [])
    evidence_refs: list[EvidenceOut] = []
    seen_ids: set[str] = set()
    for eid in ref_ids:
        if not eid or eid in seen_ids:
            continue
        seen_ids.add(eid)
        evidence = db.get(Evidence, eid)
        if evidence:
            evidence_refs.append(EvidenceOut.model_validate(evidence))
    data["evidence_refs"] = evidence_refs
    return CandidateOut(**data)


@router.get("", response_model=CandidateList)
def list_all_candidates(
    status: str | None = None,
    candidate_type: str | None = None,
    document_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> CandidateList:
    items = list_candidates(
        db,
        status=status,
        candidate_type=candidate_type,
        document_id=document_id,
        limit=limit,
        offset=offset,
    )
    return CandidateList(items=[_candidate_out(db, c) for c in items], total=len(items))


@router.get("/{candidate_id}", response_model=CandidateOut)
def get_one_candidate(candidate_id: str, db: Session = Depends(get_db)) -> CandidateOut:
    candidate = get_candidate(db, candidate_id)
    return _candidate_out(db, candidate)


@router.post("/{candidate_id}/confirm", response_model=CandidateOut)
def confirm_one_candidate(
    candidate_id: str, payload: CandidateConfirmRequest, db: Session = Depends(get_db)
) -> CandidateOut:
    candidate = get_candidate(db, candidate_id)
    confirm_candidate(
        db,
        candidate,
        reviewed_by=payload.reviewed_by,
        reason=payload.reason,
        edits=payload.edits,
    )
    db.commit()
    return _candidate_out(db, candidate)


@router.post("/{candidate_id}/reject", response_model=CandidateOut)
def reject_one_candidate(
    candidate_id: str, payload: CandidateRejectRequest, db: Session = Depends(get_db)
) -> CandidateOut:
    candidate = get_candidate(db, candidate_id)
    reject_candidate(
        db,
        candidate,
        reviewed_by=payload.reviewed_by,
        reason=payload.reason,
    )
    db.commit()
    return _candidate_out(db, candidate)


@router.put("/{candidate_id}", response_model=CandidateOut)
def edit_candidate(
    candidate_id: str, payload: CandidateUpdateRequest, db: Session = Depends(get_db)
) -> CandidateOut:
    candidate = get_candidate(db, candidate_id)
    update_candidate(
        db,
        candidate,
        proposed_data=payload.proposed_data,
        reason=payload.reason,
    )
    db.commit()
    return _candidate_out(db, candidate)
