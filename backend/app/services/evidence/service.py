"""Evidence service.

Evidence preserves the exact supporting text. Every candidate fact or
relationship is traceable to evidence, then to a source, then to the
original document.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.utils.errors import NotFoundError


def add_evidence(
    db: Session,
    *,
    document_id: str,
    source_id: str | None,
    exact_text: str,
    page_number: int | None = None,
    text_start: int | None = None,
    text_end: int | None = None,
    extraction_method: str,
    extraction_confidence: float | None = None,
) -> Evidence:
    evidence = Evidence(
        evidence_id=str(uuid.uuid4()),
        document_id=document_id,
        source_id=source_id,
        exact_text=exact_text,
        page_number=page_number,
        text_start=text_start,
        text_end=text_end,
        extraction_method=extraction_method,
        extraction_confidence=extraction_confidence,
    )
    db.add(evidence)
    db.flush()
    return evidence


def get_evidence(db: Session, evidence_id: str) -> Evidence:
    evidence = db.get(Evidence, evidence_id)
    if evidence is None:
        raise NotFoundError("Evidence not found.")
    return evidence
