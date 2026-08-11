import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.claim import Claim
from app.models.fact import Fact
from app.models.relationship import Relationship
from app.schemas.knowledge import (
    ClaimList,
    ClaimOut,
    FactList,
    FactOut,
    RelationshipCreate,
    RelationshipList,
    RelationshipOut,
)
from app.services.audit.service import log_action
from app.utils.errors import NotFoundError

router = APIRouter(tags=["knowledge"])


@router.get("/relationships", response_model=RelationshipList)
def list_relationships(
    relationship_type: str | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> RelationshipList:
    query = db.query(Relationship).order_by(Relationship.created_at.desc())
    if relationship_type:
        query = query.filter(Relationship.relationship_type == relationship_type)
    if status:
        query = query.filter(Relationship.status == status)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return RelationshipList(items=[RelationshipOut.model_validate(r) for r in items], total=total)


@router.get("/relationships/{relationship_id}", response_model=RelationshipOut)
def get_relationship(relationship_id: str, db: Session = Depends(get_db)) -> RelationshipOut:
    relationship = db.get(Relationship, relationship_id)
    if relationship is None:
        raise NotFoundError("Relationship not found.")
    return RelationshipOut.model_validate(relationship)


@router.post("/relationships", response_model=RelationshipOut, status_code=201)
def create_relationship(payload: RelationshipCreate, db: Session = Depends(get_db)) -> RelationshipOut:
    relationship = Relationship(
        relationship_id=str(uuid.uuid4()),
        source_entity_id=payload.source_entity_id,
        relationship_type=payload.relationship_type,
        target_entity_id=payload.target_entity_id,
        case_id=payload.case_id,
        event_id=payload.event_id,
        evidence_id=payload.evidence_id,
        claim_id=payload.claim_id,
        classification=payload.classification,
        status=payload.status,
        confidence=payload.confidence,
        first_observed_date=payload.first_observed_date,
        last_observed_date=payload.last_observed_date,
    )
    db.add(relationship)
    db.flush()
    log_action(
        db, action="CREATE", object_type="relationship", object_id=relationship.relationship_id,
        new_value={
            "source_entity_id": relationship.source_entity_id,
            "relationship_type": relationship.relationship_type,
            "target_entity_id": relationship.target_entity_id,
        },
        reason="relationship created via API",
    )
    db.commit()
    return RelationshipOut.model_validate(relationship)


@router.get("/facts", response_model=FactList)
def list_facts(
    predicate: str | None = None, limit: int = 200, offset: int = 0, db: Session = Depends(get_db)
) -> FactList:
    query = db.query(Fact).order_by(Fact.created_at.desc())
    if predicate:
        query = query.filter(Fact.predicate == predicate)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return FactList(items=[FactOut.model_validate(f) for f in items], total=total)


@router.get("/claims", response_model=ClaimList)
def list_claims(
    claim_status: str | None = None, limit: int = 200, offset: int = 0, db: Session = Depends(get_db)
) -> ClaimList:
    query = db.query(Claim).order_by(Claim.created_at.desc())
    if claim_status:
        query = query.filter(Claim.claim_status == claim_status)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return ClaimList(items=[ClaimOut.model_validate(c) for c in items], total=total)
