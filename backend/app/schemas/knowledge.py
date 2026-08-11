from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class RelationshipCreate(BaseModel):
    source_entity_id: str
    relationship_type: str
    target_entity_id: str
    case_id: str | None = None
    event_id: str | None = None
    evidence_id: str | None = None
    claim_id: str | None = None
    classification: str = "DIRECT"
    status: str = "CANDIDATE"
    confidence: float | None = None
    first_observed_date: date | None = None
    last_observed_date: date | None = None


class RelationshipOut(ORMModel):
    relationship_id: str
    source_entity_id: str
    relationship_type: str
    target_entity_id: str
    case_id: str | None = None
    event_id: str | None = None
    evidence_id: str | None = None
    claim_id: str | None = None
    classification: str
    status: str
    confidence: float | None = None
    first_observed_date: date | None = None
    last_observed_date: date | None = None
    created_at: datetime
    updated_at: datetime


class RelationshipList(BaseModel):
    items: list[RelationshipOut]
    total: int = 0


class FactOut(ORMModel):
    fact_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str | None = None
    event_id: str | None = None
    case_id: str | None = None
    evidence_id: str | None = None
    status: str
    confidence: float | None = None
    created_at: datetime
    updated_at: datetime


class FactList(BaseModel):
    items: list[FactOut]
    total: int = 0


class ClaimOut(ORMModel):
    claim_id: str
    claim_text: str
    claim_status: str
    evidence_id: str | None = None
    subject_entity_id: str | None = None
    created_at: datetime


class ClaimList(BaseModel):
    items: list[ClaimOut]
    total: int = 0
