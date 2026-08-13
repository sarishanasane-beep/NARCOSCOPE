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
from app.models.document import Document
from app.models.entity import (
    ENTITY_STATUS_ACTIVE,
    ENTITY_STATUS_MERGED,
    ENTITY_TYPE_CASE,
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
from app.services.entities.duplicates import reconcile_case_entity
from app.services.entities.resolution import create_entity, find_entity_by_name
from app.utils.errors import CandidateStateError, ValidationError
from app.utils.text import normalize_case_number, normalize_name
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

    # Structured-source semantics survive confirmation in Entity.metadata
    # so the Network Explorer can distinguish a contextual/mentioned-only
    # person from an investigative subject — never inferred, only the
    # explicit fields plus the neutral MENTIONED_ONLY default for a person
    # with no documented investigative status.
    structured_meta: dict = {}
    for key in (
        "structured_kind", "role", "status", "mention_context", "location_type",
        "description", "quantity", "value", "registration",
    ):
        value = proposed.get(key)
        if value:
            structured_meta[key] = value
    if entity_type == ENTITY_TYPE_PERSON:
        structured_meta["investigative_status"] = _derive_investigative_status(proposed)
    if candidate.evidence_id:
        evidence = db.get(Evidence, candidate.evidence_id)
        if evidence and evidence.exact_text:
            structured_meta["evidence_snippet"] = evidence.exact_text[:300]

    entity = create_entity(
        db,
        entity_type=entity_type,
        canonical_name=name,
        aliases=aliases,
        notes=notes,
        parent_location=parent_location,
        organization_type=organization_type,
        location_type=proposed.get("location_type") or "OTHER",
        structured_metadata=structured_meta or None,
        document_id=candidate.source_document_id,
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
    # Exact TIME text from the source — kept as written, "Not provided"
    # when absent. Never derived from publication/upload timestamps.
    event_time = (proposed.get("time") or proposed.get("event_time") or "").strip() or None

    location_id = None
    location_name = proposed.get("location_name")
    if location_name:
        location = find_entity_by_name(db, location_name, ENTITY_TYPE_LOCATION)
        if location is None:
            # Exact-name fallback: a location entity whose canonical name is
            # contained in the source string ("Mumbai region" -> Mumbai).
            # Deterministic; the longest contained name wins.
            location = _find_contained_location(db, location_name)
        if location is not None and location.location is not None:
            location_id = location.location.location_id

    case_id = _resolve_case_ref(db, proposed.get("case_ref"))
    if case_id is None and candidate.source_document_id:
        # One structured document = one case: events inherit the case of
        # their source document so /timeline/case and the case graph agree.
        document = db.get(Document, candidate.source_document_id)
        if document is not None:
            case_id = document.case_id

    event_meta: dict = {}
    for key in ("status", "duration", "organization", "drug", "vehicle", "person"):
        value = proposed.get(key)
        if value:
            event_meta[key] = value
    if proposed.get("accused_identity"):
        event_meta["accused_identity"] = proposed["accused_identity"]
    if proposed.get("quantity"):
        event_meta["quantity"] = proposed["quantity"]
    if proposed.get("value"):
        event_meta["value"] = proposed["value"]
    if candidate.evidence_id:
        evidence = db.get(Evidence, candidate.evidence_id)
        if evidence and evidence.exact_text:
            event_meta["evidence_snippet"] = evidence.exact_text[:300]

    event = Event(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        title=title,
        description=proposed.get("description"),
        start_date=start_date,
        end_date=end_date,
        date_precision=precision,
        event_time=event_time,
        location_id=location_id,
        case_id=case_id,
        document_id=candidate.source_document_id,
        evidence_id=candidate.evidence_id,
        structured_metadata=event_meta or None,
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

    # A CASE-typed endpoint represents a declared CASE (e.g. the operation
    # node for "Operation WHITE STRIKE"). Resolve the canonical Case FIRST
    # so a CASE-typed endpoint reuses/reconciles into it instead of
    # creating an independent CASE record (ingestion-time prevention). The
    # entity endpoint still exists (the graph requires entity endpoints)
    # but is reconciled to the Case and never appears on its own.
    case_id = None
    if source_type == ENTITY_TYPE_CASE:
        case_id = _find_case_id_by_name(db, source_name)
    if target_type == ENTITY_TYPE_CASE:
        case_id = case_id or _find_case_id_by_name(db, target_name)

    source = _resolve_endpoint_entity(db, source_name, source_type, user, linked_case_id=case_id)
    target = _resolve_endpoint_entity(db, target_name, target_type, user, linked_case_id=case_id)

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
        case_id=case_id,
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
    case_id: str | None = None

    if action == "link" and proposed.get("existing_case_id"):
        existing = db.get(Case, proposed["existing_case_id"])
        if existing is not None:
            case_id = existing.case_id
            log_action(
                db, action="CONFIRM", object_type="case_match", object_id=existing.case_id,
                new_value={"case_id": existing.case_id, "decision": "same case"},
                reason="reviewer confirmed the case match", user=user,
            )
    if case_id is None:
        existing_id, _ = match_case(db, case_number=case_number, case_name=case_name)
        if existing_id:
            existing = db.get(Case, existing_id)
            case_id = existing.case_id
            log_action(
                db, action="CONFIRM", object_type="case_match", object_id=existing.case_id,
                new_value={"case_id": existing.case_id, "decision": "linked to existing case"},
                reason="reviewer confirmed the case match", user=user,
            )
    if case_id is None:
        case = Case(
            case_id=str(uuid.uuid4()),
            official_case_number=case_number,
            case_name=case_name,
            jurisdiction=jurisdiction,
            category=proposed.get("category"),
            status=proposed.get("status") or "UNKNOWN",
            description=proposed.get("description"),
        )
        db.add(case)
        db.flush()
        case_id = case.case_id
        log_action(
            db, action="CREATE", object_type="case", object_id=case.case_id,
            new_value={"official_case_number": case_number, "case_name": case_name},
            reason="candidate confirmation", user=user,
        )

    # One structured TXT document = one case: the source document is linked
    # to the case so events and isolated entities from the same document
    # can be scoped to the case without fabricating membership edges.
    if candidate.source_document_id:
        document = db.get(Document, candidate.source_document_id)
        if document is not None and document.case_id is None:
            document.case_id = case_id
    return case_id, "case"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Investigative-status vocabulary. These are the ONLY values NARCOSCOPE
# assigns to a person's investigative status; the value always comes from
# the explicit structured fields or the neutral MENTIONED_ONLY default.
# ARRESTED/APPREHENDED are legal-process facts and are NOT investigative
# statuses — an accused status comes only from an explicit ROLE/STATUS.
_INVESTIGATIVE_STATUSES = {
    "INVOLVED",
    "SUSPECT",
    "ACCUSED",
    "WITNESS",
    "VICTIM",
    "PERSON_OF_INTEREST",
    "MENTIONED_ONLY",
    "CONTEXTUAL",
    "UNKNOWN",
}


def _derive_investigative_status(proposed: dict) -> str:
    """Deterministic, non-inferring investigative status for a PERSON.

    Priority: explicit CONTEXTUAL mention context, then an explicit status
    or role that is part of the vocabulary, then the neutral
    MENTIONED_ONLY default. A person mentioned in a source with no
    documented investigative status is MENTIONED_ONLY — this is the
    absence of an allegation, never an allegation itself.
    """
    explicit = (proposed.get("investigative_status") or "").strip().upper()
    status = (proposed.get("status") or "").strip().upper()
    role = (proposed.get("role") or "").strip().upper()
    context = (proposed.get("mention_context") or "").strip().upper()
    # An explicitly declared INVESTIGATIVE_STATUS field (v2 contract) is
    # authoritative when it is part of the vocabulary.
    if explicit in _INVESTIGATIVE_STATUSES:
        return explicit
    if "CONTEXTUAL" in (status, role, context):
        return "CONTEXTUAL"
    if status in _INVESTIGATIVE_STATUSES:
        return status
    if role in _INVESTIGATIVE_STATUSES:
        return role
    return "MENTIONED_ONLY"


def _resolve_endpoint_entity(
    db: Session,
    name: str,
    entity_type: str,
    user: str | None,
    linked_case_id: str | None = None,
) -> Entity:
    """Find a confirmed entity by name; create it if missing.

    Endpoint entities come from the same document's candidates; creating
    them during relationship confirmation is safe because the reviewer
    explicitly accepted the relationship.

    For CASE-typed endpoints with a resolved canonical Case, the endpoint
    is the case's reconciled entity (reused if present, created and
    immediately reconciled otherwise) — confirming more relationships
    never fabricates independent CASE records.
    """
    if entity_type == ENTITY_TYPE_CASE and linked_case_id:
        return _resolve_case_endpoint(db, name, linked_case_id, user)
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


def _resolve_case_endpoint(
    db: Session, name: str, case_id: str, user: str | None
) -> Entity:
    """CASE-typed relationship-endpoint entity for a canonical Case.

    Reuses an existing endpoint (ACTIVE, or already reconciled into this
    case); otherwise creates one and immediately reconciles it into the
    case so it never appears as an independent logical record. The graph
    service routes edges from reconciled endpoints to the case node.
    """
    normalized = normalize_name(name)
    for entity in db.query(Entity).filter(Entity.entity_type == ENTITY_TYPE_CASE).all():
        if normalize_name(entity.canonical_name) != normalized:
            continue
        if entity.status == ENTITY_STATUS_ACTIVE:
            return entity
        if entity.status == ENTITY_STATUS_MERGED and entity.merged_into_case_id == case_id:
            return entity
    entity = create_entity(
        db,
        entity_type=ENTITY_TYPE_CASE,
        canonical_name=name,
        notes="CASE endpoint created during relationship confirmation.",
        user=user,
    )
    reconcile_case_entity(
        db, entity.entity_id, case_id,
        user=user,
        note="CASE endpoint reconciled into its canonical Case at confirmation.",
    )
    return entity


def _find_contained_location(db: Session, location_name: str) -> Entity | None:
    """A location entity whose canonical name is contained in the string.

    Exact matches are handled before this helper. Longest contained name
    wins ("KWC Warehousing Complex, Sector KWC, Kalamboli" ->
    "KWC Warehousing Complex", not "Kalamboli"). Only ACTIVE locations.
    """
    needle = location_name.lower()
    best: tuple[Entity, int] | None = None
    for entity in (
        db.query(Entity)
        .filter(Entity.entity_type == ENTITY_TYPE_LOCATION, Entity.status == ENTITY_STATUS_ACTIVE)
        .all()
    ):
        name = (entity.canonical_name or "").lower()
        if name and name in needle and len(name) > 1:
            if best is None or len(name) > best[1]:
                best = (entity, len(name))
    return best[0] if best is not None else None


def _find_case_id_by_name(db: Session, name: str) -> str | None:
    """Exact normalized-name lookup for a confirmed Case record."""
    bare = _CASE_LABEL_PREFIX.sub("", name).strip()
    if not bare:
        return None
    normalized = normalize_case_number(bare)
    for case in db.query(Case).all():
        candidate = case.case_name or case.official_case_number or ""
        if candidate and normalize_case_number(candidate) == normalized:
            return case.case_id
    return None


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
