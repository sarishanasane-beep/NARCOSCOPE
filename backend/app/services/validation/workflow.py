"""Validation workflow.

EXTRACT -> CANDIDATE -> REVIEW (CONFIRM / EDIT / REJECT) -> TRUSTED DATA

Confirmation validates the candidate, creates/updates the trusted record,
preserves evidence, creates an audit entry and marks the candidate
confirmed. Rejection preserves the candidate record and keeps it out of
trusted data.
"""

from __future__ import annotations

import re
import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.candidate import (
    CANDIDATE_STATUS_CONFIRMED,
    CANDIDATE_STATUS_EDITED,
    CANDIDATE_STATUS_PENDING,
    CANDIDATE_TYPE_CASE_MATCH,
    CANDIDATE_TYPE_ENTITY,
    CANDIDATE_TYPE_EVENT,
    CANDIDATE_TYPE_FACT,
    CANDIDATE_TYPE_LOCATION,
    CANDIDATE_TYPE_RELATIONSHIP,
    Candidate,
)
from app.models.case import Case
from app.models.entity import (
    ENTITY_TYPE_LOCATION,
    ENTITY_TYPE_ORGANIZATION,
    ENTITY_TYPE_PERSON,
    Entity,
)
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
from app.services.audit.service import log_action
from app.services.cases.matching import match_case
from app.services.entities.resolution import create_entity, find_entity_by_name
from app.utils.errors import CandidateStateError, ValidationError
from app.utils.text import normalize_case_number
from app.utils.logging import log_event
from app.utils.time import utcnow

import logging

logger = logging.getLogger(__name__)


def confirm_candidate(
    db: Session,
    candidate: Candidate,
    *,
    reviewed_by: str | None = None,
    reason: str | None = None,
    edits: dict[str, Any] | None = None,
) -> Candidate:
    """Confirm a candidate, materializing the trusted record."""
    if candidate.status not in (CANDIDATE_STATUS_PENDING, CANDIDATE_STATUS_EDITED):
        raise CandidateStateError("Candidate is not in a reviewable state.")

    if edits:
        previous = dict(candidate.proposed_data or {})
        candidate.proposed_data = {**(candidate.proposed_data or {}), **edits}
        candidate.status = CANDIDATE_STATUS_EDITED
        log_action(
            db,
            action="UPDATE",
            object_type="candidate",
            object_id=candidate.candidate_id,
            previous_value=previous,
            new_value=candidate.proposed_data,
            reason="edits applied during confirmation",
            user=reviewed_by,
        )

    proposed = candidate.proposed_data or {}
    trusted_id: str | None = None
    trusted_type: str | None = None

    if candidate.candidate_type in (CANDIDATE_TYPE_ENTITY, CANDIDATE_TYPE_LOCATION):
        trusted_id, trusted_type = _resolve_entity(db, candidate, proposed, reviewed_by)
    elif candidate.candidate_type == CANDIDATE_TYPE_EVENT:
        trusted_id, trusted_type = _resolve_event(db, candidate, proposed, reviewed_by)
    elif candidate.candidate_type == CANDIDATE_TYPE_RELATIONSHIP:
        trusted_id, trusted_type = _resolve_relationship(db, candidate, proposed, reviewed_by)
    elif candidate.candidate_type == CANDIDATE_TYPE_FACT:
        trusted_id, trusted_type = _resolve_fact(db, candidate, proposed, reviewed_by)
    elif candidate.candidate_type == CANDIDATE_TYPE_CASE_MATCH:
        trusted_id, trusted_type = _resolve_case(db, candidate, proposed, reviewed_by)
    else:  # pragma: no cover
        raise ValidationError(f"Unsupported candidate type: {candidate.candidate_type}")

    candidate.status = CANDIDATE_STATUS_CONFIRMED
    candidate.reviewed_at = utcnow()
    candidate.reviewed_by = reviewed_by
    db.flush()

    log_action(
        db,
        action="CONFIRM",
        object_type="candidate",
        object_id=candidate.candidate_id,
        new_value={"status": CANDIDATE_STATUS_CONFIRMED, "trusted_id": trusted_id, "trusted_type": trusted_type},
        reason=reason or "confirmed by reviewer",
        user=reviewed_by,
    )
    log_event(
        logger, "candidate_confirmed",
        candidate_id=candidate.candidate_id, candidate_type=candidate.candidate_type,
        trusted_id=trusted_id, user=reviewed_by,
    )
    return candidate


# ---------------------------------------------------------------------------
# Trusted-record resolvers
# ---------------------------------------------------------------------------


def _resolve_entity(
    db: Session, candidate: Candidate, proposed: dict, user: str | None
) -> tuple[str, str]:
    name = _require(proposed, "name")
    entity_type = proposed.get("entity_type") or "OTHER"
    aliases = proposed.get("aliases") or []
    parent_location = proposed.get("parent_location")
    organization_type = proposed.get("organization_type") or "ORGANIZATION"
    notes = f"Confirmed from document {candidate.source_document_id}."
    if candidate.evidence_id:
        evidence = db.get(Evidence, candidate.evidence_id)
        if evidence:
            notes += f" Evidence: {evidence.exact_text[:300]}"

    entity = create_entity(
        db,
        entity_type=entity_type,
        canonical_name=name,
        aliases=aliases,
        notes=notes,
        parent_location=parent_location,
        organization_type=organization_type,
        user=user,
    )
    return entity.entity_id, "entity"


def _resolve_event(
    db: Session, candidate: Candidate, proposed: dict, user: str | None
) -> tuple[str, str]:
    event_type = proposed.get("event_type") or "OTHER"
    title = _require(proposed, "title")
    start_date = _parse_date(proposed.get("start_date"))
    end_date = _parse_date(proposed.get("end_date"))
    precision = proposed.get("date_precision") or "UNKNOWN"

    location_id = None
    location_name = proposed.get("location_name")
    if location_name:
        location = find_entity_by_name(db, location_name, ENTITY_TYPE_LOCATION)
        if location is not None and location.location is not None:
            location_id = location.location.location_id

    case_id = _resolve_case_ref(db, proposed.get("case_ref"))

    event = Event(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        title=title,
        start_date=start_date,
        end_date=end_date,
        date_precision=precision,
        location_id=location_id,
        case_id=case_id,
    )
    db.add(event)
    db.flush()
    log_action(
        db, action="CREATE", object_type="event", object_id=event.event_id,
        new_value={"event_type": event_type, "title": title, "date_precision": precision},
        reason="candidate confirmation", user=user,
    )
    return event.event_id, "event"


def _resolve_relationship(
    db: Session, candidate: Candidate, proposed: dict, user: str | None
) -> tuple[str, str]:
    source_name = _require(proposed, "source_name")
    source_type = proposed.get("source_type") or ENTITY_TYPE_PERSON
    target_name = _require(proposed, "target_name")
    target_type = proposed.get("target_type") or ENTITY_TYPE_OTHER
    relationship_type = _require(proposed, "relationship_type")
    classification = proposed.get("classification") or "DIRECT"

    source = _resolve_endpoint_entity(db, source_name, source_type, user)
    target = _resolve_endpoint_entity(db, target_name, target_type, user)

    event_id = None
    if target_type != ENTITY_TYPE_LOCATION:
        event = db.query(Event).filter(Event.title == target_name).first()
        if event:
            event_id = event.event_id

    relationship = Relationship(
        relationship_id=str(uuid.uuid4()),
        source_entity_id=source.entity_id,
        relationship_type=relationship_type,
        target_entity_id=target.entity_id,
        event_id=event_id,
        evidence_id=candidate.evidence_id,
        classification=classification,
        status=REL_STATUS_CONFIRMED,
        confidence=candidate.confidence,
    )
    db.add(relationship)
    db.flush()
    log_action(
        db, action="CREATE", object_type="relationship", object_id=relationship.relationship_id,
        new_value={
            "source_entity_id": source.entity_id,
            "relationship_type": relationship_type,
            "target_entity_id": target.entity_id,
            "classification": classification,
        },
        reason="candidate confirmation", user=user,
    )
    return relationship.relationship_id, "relationship"


def _resolve_fact(
    db: Session, candidate: Candidate, proposed: dict, user: str | None
) -> tuple[str, str]:
    subject_name = _require(proposed, "subject_name")
    predicate = _require(proposed, "predicate")
    subject_type = proposed.get("subject_type") or ENTITY_TYPE_PERSON
    subject = _resolve_endpoint_entity(db, subject_name, subject_type, user)

    object_entity_id = None
    object_name = proposed.get("object_name")
    object_type = proposed.get("object_type")
    if object_name and object_type == "entity":
        object_entity = _resolve_endpoint_entity(db, object_name, ENTITY_TYPE_OTHER, user)
        object_entity_id = object_entity.entity_id

    case_id = _resolve_case_ref(db, proposed.get("case_ref"))
    event_id = None
    event_ref = proposed.get("event_ref")
    if event_ref:
        event = db.query(Event).filter(Event.title == event_ref).first()
        if event:
            event_id = event.event_id

    fact = Fact(
        fact_id=str(uuid.uuid4()),
        subject_entity_id=subject.entity_id,
        predicate=predicate,
        object_entity_id=object_entity_id,
        event_id=event_id,
        case_id=case_id,
        evidence_id=candidate.evidence_id,
        status=FACT_STATUS_CONFIRMED,
        confidence=candidate.confidence,
    )
    db.add(fact)
    db.flush()
    log_action(
        db, action="CREATE", object_type="fact", object_id=fact.fact_id,
        new_value={"subject_entity_id": subject.entity_id, "predicate": predicate, "case_id": case_id},
        reason="candidate confirmation", user=user,
    )
    return fact.fact_id, "fact"


def _resolve_case(
    db: Session, candidate: Candidate, proposed: dict, user: str | None
) -> tuple[str, str]:
    action = proposed.get("action") or "create"
    case_number = proposed.get("case_number")
    case_name = proposed.get("case_name")
    jurisdiction = proposed.get("jurisdiction")

    if action == "link" and proposed.get("existing_case_id"):
        existing = db.get(Case, proposed["existing_case_id"])
        if existing is not None:
            log_action(
                db, action="CONFIRM", object_type="case_match", object_id=existing.case_id,
                new_value={"case_id": existing.case_id, "decision": "same case"},
                reason="reviewer confirmed the case match", user=user,
            )
            return existing.case_id, "case"

    existing_id, _ = match_case(db, case_number=case_number, case_name=case_name)
    if existing_id:
        existing = db.get(Case, existing_id)
        log_action(
            db, action="CONFIRM", object_type="case_match", object_id=existing.case_id,
            new_value={"case_id": existing.case_id, "decision": "linked to existing case"},
            reason="reviewer confirmed the case match", user=user,
        )
        return existing.case_id, "case"

    case = Case(
        case_id=str(uuid.uuid4()),
        official_case_number=case_number,
        case_name=case_name,
        jurisdiction=jurisdiction,
        status="UNKNOWN",
    )
    db.add(case)
    db.flush()
    log_action(
        db, action="CREATE", object_type="case", object_id=case.case_id,
        new_value={"official_case_number": case_number, "case_name": case_name},
        reason="candidate confirmation", user=user,
    )
    return case.case_id, "case"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_endpoint_entity(
    db: Session, name: str, entity_type: str, user: str | None
) -> Entity:
    """Find a confirmed entity by name; create it if missing.

    Endpoint entities come from the same document's candidates; creating
    them during relationship confirmation is safe because the reviewer
    explicitly accepted the relationship.
    """
    entity = find_entity_by_name(db, name, entity_type)
    if entity is not None:
        return entity
    return create_entity(
        db,
        entity_type=entity_type,
        canonical_name=name,
        notes="Created during relationship/fact confirmation.",
        user=user,
    )


# "Case CASE-001" / "Case No. CASE-001" — a leading case label is not
# part of the official number, so it is stripped before name matching.
_CASE_LABEL_PREFIX = re.compile(r"^(?:case\s+(?:no\.?\s*|number\s*)?)", re.IGNORECASE)


def _resolve_case_ref(db: Session, case_ref: str | None) -> str | None:
    if not case_ref:
        return None
    # 1) Exact official number ("NCB/MUM/123/2026").
    existing_id, _ = match_case(db, case_number=case_ref, case_name=case_ref)
    if existing_id:
        return existing_id
    # 2) Label-form reference ("Case CASE-001") naming an already-registered
    #    case (official number + label): link by EXACT case name so facts/
    #    events confirmed after the case match reuse the REAL case record
    #    instead of creating a fresh case-name-only duplicate. The match is
    #    exact (normalized equality) — never fuzzy, never an auto-merge.
    bare = _CASE_LABEL_PREFIX.sub("", case_ref).strip()
    if bare:
        for candidate in db.query(Case).all():
            if candidate.case_name and normalize_case_number(candidate.case_name) == normalize_case_number(bare):
                log_action(
                    db, action="CONFIRM", object_type="case_match", object_id=candidate.case_id,
                    new_value={"case_id": candidate.case_id, "decision": "linked to existing case by name"},
                    reason="resolved while confirming a fact",
                )
                return candidate.case_id
    case = Case(case_id=str(uuid.uuid4()), case_name=case_ref, status="UNKNOWN")
    db.add(case)
    db.flush()
    log_action(
        db, action="CREATE", object_type="case", object_id=case.case_id,
        new_value={"case_name": case_ref}, reason="created while resolving a fact",
    )
    return case.case_id


def _parse_date(value: Any) -> date_type | None:
    if not value:
        return None
    if isinstance(value, date_type):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date_type.fromisoformat(value)
        except ValueError:
            return None
    return None


def _require(proposed: dict, key: str) -> str:
    value = proposed.get(key)
    if not value:
        raise ValidationError(f"Candidate is missing required field: {key}")
    return str(value)
