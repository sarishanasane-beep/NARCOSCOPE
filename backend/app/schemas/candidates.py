from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.evidence import EvidenceOut


class CandidateOut(ORMModel):
    candidate_id: str
    candidate_type: str
    proposed_data: dict[str, Any]
    source_document_id: str | None = None
    evidence_id: str | None = None
    confidence: float | None = None
    reason: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None

    # Populated by the API layer (not an ORM attribute).
    evidence: EvidenceOut | None = None

    # Populated by the API layer: every evidence occurrence for the
    # candidate (one canonical candidate, many evidence references).
    evidence_refs: list[EvidenceOut] = []

    # Populated by the API layer: explains that the score is extraction/
    # matching confidence, never a probability of guilt.
    confidence_meaning: str | None = None


class CandidateList(BaseModel):
    items: list[CandidateOut]
    total: int = 0


class CandidateConfirmRequest(BaseModel):
    reviewed_by: str | None = None
    reason: str | None = None
    edits: dict[str, Any] | None = None


class CandidateRejectRequest(BaseModel):
    reviewed_by: str | None = None
    reason: str | None = None


class CandidateUpdateRequest(BaseModel):
    proposed_data: dict[str, Any]
    reason: str | None = None
