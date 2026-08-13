"""Candidate service.

Persistence of extraction results as candidates + evidence, plus
queries. The review workflow (confirm / reject / edit) lives in
``app.services.validation.workflow``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.candidate import (
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
from app.models.claim import Claim
from app.models.document import Document
from app.models.entity import Entity
from app.models.evidence import Evidence
from app.models.source import Source
from app.services.audit.service import log_action
from app.services.documents.segments import page_for_offset
from app.services.evidence.service import add_evidence
from app.services.extraction.engine import ExtractionResult, evidence_span_for
from app.services.extraction.relationships import RelationshipCandidate
from app.services.extraction.resolution import possible_match_against_existing
from app.utils.errors import CandidateStateError, NotFoundError
from app.utils.logging import log_event
from app.utils.text import normalize_name
from app.utils.time import utcnow

import logging

logger = logging.getLogger(__name__)

ENTITY_TYPES = {
    "PERSON": "PERSON",
    "AGENCY": "AGENCY",
    "ORGANIZATION": "ORGANIZATION",
    "LOCATION": "LOCATION",
    "PROPERTY": "PROPERTY",
    "OTHER": "OTHER",
}

# Structured-document metadata carried through from the parser into the
# candidate's proposed data (reviewer-facing; generic documents never set
# these keys). The *_id keys preserve the authoritative structured IDs
# (ENTITY_ID / EVENT_ID / RELATIONSHIP_ID / FACT_ID / CASE_ID) so the
# reviewer can trace a candidate back to its declared block.
_STRUCTURED_META_KEYS = (
    "role", "status", "quantity", "registration", "value", "sentence",
    "court", "location_type", "structured_kind", "description",
    "mention_context", "duration", "organization", "accused_identity",
    "time", "date_precision", "drug", "vehicle", "person",
    "evidence_snippet", "type_conflicts", "investigative_status",
    "entity_id", "event_id", "relationship_id", "fact_id",
)


def _structured_meta(extra: dict | None) -> dict:
    result = {}
    for key in _STRUCTURED_META_KEYS:
        value = (extra or {}).get(key)
        if value not in (None, ""):
            result[key] = value
    return result


@dataclass
class PersistStats:
    candidates: int = 0
    evidence: int = 0
    claims: int = 0


def persist_extraction(
    db: Session,
    *,
    document: Document,
    source: Source | None,
    result: ExtractionResult,
    segments: list,
) -> PersistStats:
    """Store evidence + candidates (+ claims) for an extraction result."""
    stats = PersistStats()
    evidence_by_span: dict[tuple[int, int], Evidence] = {}

    # Cross-document entity-resolution context: known persons already in
    # the database (confirmed entities + pending/edited candidates from
    # earlier documents) and existing POSSIBLE_MATCH pairs. Gathered
    # BEFORE this document's candidates are added, so the queries can
    # never autoflush (and then include) the current document's rows.
    existing_names, existing_match_pairs = _existing_person_forms(db)

    def _evidence_for(span) -> Evidence:
        key = (span.start, span.end)
        if key in evidence_by_span:
            return evidence_by_span[key]
        evidence = add_evidence(
            db,
            document_id=document.document_id,
            source_id=source.source_id if source else None,
            exact_text=span.text,
            page_number=page_for_offset(segments, span.start),
            text_start=span.start,
            text_end=span.end,
            extraction_method="deterministic_rules",
        )
        evidence_by_span[key] = evidence
        stats.evidence += 1
        return evidence

    def _context_span(span) -> "object":
        return evidence_span_for(span, result.sentences)

    # Claims are stored directly (they preserve the source's stance —
    # an allegation remains an allegation).
    for claim in result.claims:
        evidence = _evidence_for(claim.span)
        db.add(
            Claim(
                claim_id=str(uuid.uuid4()),
                claim_text=claim.claim_text,
                claim_status=claim.claim_status,
                evidence_id=evidence.evidence_id,
                subject_entity_id=None,
            )
        )
        stats.claims += 1

    # Entities — one canonical candidate per (type, normalized name).
    # Every occurrence keeps its own evidence reference, and the same
    # entity seen in another document merges into the existing pending
    # candidate instead of creating a duplicate the reviewer must
    # confirm again.
    for entity in result.entities:
        candidate_type = (
            CANDIDATE_TYPE_LOCATION
            if entity.entity_type == "LOCATION"
            else CANDIDATE_TYPE_ENTITY
        )
        spans = [entity.span]
        for span in entity.extra.get("occurrence_spans") or []:
            if span not in spans:
                spans.append(span)
        evidence_ids: list[str] = []
        for span in spans:
            evidence = _evidence_for(_context_span(span))
            if evidence.evidence_id not in evidence_ids:
                evidence_ids.append(evidence.evidence_id)

        existing = _find_pending_entity_candidate(
            db, candidate_type, entity.entity_type, entity.normalized_name
        )
        if existing is not None:
            refs = list(existing.proposed_data.get("evidence_refs") or [])
            if existing.evidence_id and existing.evidence_id not in refs:
                refs.append(existing.evidence_id)
            for eid in evidence_ids:
                if eid not in refs:
                    refs.append(eid)
            # Reassign the whole dict: the JSON column has no mutation
            # tracking, so an in-place change would be silently lost at
            # commit and the new evidence reference would never persist.
            existing.proposed_data = {
                **(existing.proposed_data or {}),
                **_structured_meta(entity.extra),
                "evidence_refs": refs,
            }
        else:
            db.add(
                Candidate(
                    candidate_id=str(uuid.uuid4()),
                    candidate_type=candidate_type,
                    proposed_data={
                        "name": entity.name,
                        "entity_type": entity.entity_type,
                        "aliases": entity.aliases,
                        "parent_location": entity.extra.get("parent_location"),
                        "organization_type": entity.extra.get("organization_type"),
                        **_structured_meta(entity.extra),
                        "evidence_refs": evidence_ids,
                    },
                    source_document_id=document.document_id,
                    evidence_id=evidence_ids[0] if evidence_ids else None,
                    confidence=entity.confidence,
                    reason=entity.reason,
                    status=CANDIDATE_STATUS_PENDING,
                )
            )
            stats.candidates += 1

    # Cross-document entity resolution: newly extracted persons compared
    # against known persons from earlier documents. Distinct-but-similar
    # forms (initial forms, strict subsets) become POSSIBLE_MATCH
    # candidates — classification CANDIDATE, confidence 0.6, human
    # confirmation required. Exact canonical names were already merged
    # above; nothing here is ever auto-merged.
    cross_doc_matches = possible_match_against_existing(
        result.entities,
        existing_names=existing_names,
        existing_pairs=existing_match_pairs,
    )
    result.relationships = _dedupe_possible_matches(result.relationships + cross_doc_matches)

    # Events
    for event in result.events:
        evidence = _evidence_for(event.span)
        start_date = event.date.to_iso() if event.date else None
        end_date = None
        precision = event.date.precision if event.date else "UNKNOWN"
        if precision == "RANGE" and event.date and event.date.original:
            end = max(
                (d for d in result.dates if d.original == event.date.original and d.normalized),
                key=lambda d: d.normalized,
                default=None,
            )
            end_date = end.to_iso() if end else None
        db.add(
            Candidate(
                candidate_id=str(uuid.uuid4()),
                candidate_type=CANDIDATE_TYPE_EVENT,
                proposed_data={
                    "event_type": event.event_type,
                    "title": event.title,
                    "start_date": start_date,
                    "end_date": end_date,
                    "date_precision": precision,
                    "location_name": event.location_name,
                    "case_ref": event.case_ref,
                    **_structured_meta(event.extra),
                },
                source_document_id=document.document_id,
                evidence_id=evidence.evidence_id,
                confidence=event.confidence,
                reason=event.reason,
                status=CANDIDATE_STATUS_PENDING,
            )
        )
        stats.candidates += 1

    # Relationships
    for relationship in result.relationships:
        evidence = _evidence_for(relationship.span)
        db.add(
            Candidate(
                candidate_id=str(uuid.uuid4()),
                candidate_type=CANDIDATE_TYPE_RELATIONSHIP,
                proposed_data={
                    "source_name": relationship.source_name,
                    "source_type": relationship.source_type,
                    "relationship_type": relationship.relationship_type,
                    "target_name": relationship.target_name,
                    "target_type": relationship.target_type,
                    "classification": relationship.classification,
                    **_structured_meta(relationship.extra),
                },
                source_document_id=document.document_id,
                evidence_id=evidence.evidence_id,
                confidence=relationship.confidence,
                reason=relationship.reason,
                status=CANDIDATE_STATUS_PENDING,
            )
        )
        stats.candidates += 1

    # Facts
    for fact in result.facts:
        evidence = _evidence_for(fact.span)
        db.add(
            Candidate(
                candidate_id=str(uuid.uuid4()),
                candidate_type=CANDIDATE_TYPE_FACT,
                proposed_data={
                    "subject_name": fact.subject_name,
                    "subject_type": fact.subject_type,
                    "predicate": fact.predicate,
                    "object_name": fact.object_name,
                    "object_type": fact.object_type,
                    "case_ref": fact.case_ref,
                    **_structured_meta(fact.extra),
                },
                source_document_id=document.document_id,
                evidence_id=evidence.evidence_id,
                confidence=fact.confidence,
                reason=fact.reason,
                status=CANDIDATE_STATUS_PENDING,
            )
        )
        stats.candidates += 1

    # Case matches
    for case in result.cases:
        evidence = _evidence_for(case.span) if case.span else None
        db.add(
            Candidate(
                candidate_id=str(uuid.uuid4()),
                candidate_type=CANDIDATE_TYPE_CASE_MATCH,
                proposed_data={
                    "case_number": case.case_number,
                    "case_name": case.case_name,
                    "action": case.action,
                    "existing_case_id": case.existing_case_id,
                    "jurisdiction": case.jurisdiction,
                    "category": case.category,
                    "status": case.status,
                    "description": case.description,
                    "structured_id": case.structured_id,
                },
                source_document_id=document.document_id,
                evidence_id=evidence.evidence_id if evidence else None,
                confidence=case.confidence,
                reason=case.reason,
                status=CANDIDATE_STATUS_PENDING,
            )
        )
        stats.candidates += 1

    db.flush()
    log_event(
        logger,
        "candidates_created",
        document_id=document.document_id,
        count=stats.candidates,
        evidence=stats.evidence,
        claims=stats.claims,
    )
    return stats


def _find_pending_entity_candidate(
    db: Session,
    candidate_type: str,
    entity_type: str,
    normalized_name: str,
) -> Candidate | None:
    """Find an existing reviewable entity candidate for the same entity.

    Matches pending/edited entity candidates of the same entity type and
    normalized name from any document, so the same entity seen in several
    documents produces one canonical candidate with multiple evidence
    references instead of duplicate candidates.
    """
    for candidate in (
        db.query(Candidate)
        .filter(
            Candidate.candidate_type.in_([CANDIDATE_TYPE_ENTITY, CANDIDATE_TYPE_LOCATION]),
            Candidate.status.in_([CANDIDATE_STATUS_PENDING, CANDIDATE_STATUS_EDITED]),
        )
        .all()
    ):
        proposed = candidate.proposed_data or {}
        if proposed.get("entity_type") != entity_type:
            continue
        if normalize_name(proposed.get("name") or "") != normalized_name:
            continue
        return candidate
    return None


def _existing_person_forms(db: Session) -> tuple[set[str], set[tuple[str, str]]]:
    """Known person names and existing POSSIBLE_MATCH pairs.

    Names come from confirmed entities (trusted data) and pending/edited
    entity candidates (earlier documents awaiting review). The returned
    pairs are already-normalized (source, target) keys of existing
    POSSIBLE_MATCH candidates, so repeat mentions of the same variant in
    later documents do not create duplicate possible matches.
    """
    names: set[str] = set()
    for entity in db.query(Entity).filter(Entity.entity_type == "PERSON").all():
        names.add(entity.canonical_name)
    for candidate in (
        db.query(Candidate)
        .filter(
            Candidate.candidate_type.in_([CANDIDATE_TYPE_ENTITY, CANDIDATE_TYPE_LOCATION]),
            Candidate.status.in_([CANDIDATE_STATUS_PENDING, CANDIDATE_STATUS_EDITED]),
        )
        .all()
    ):
        proposed = candidate.proposed_data or {}
        if proposed.get("entity_type") == "PERSON" and proposed.get("name"):
            names.add(proposed["name"])
    pairs: set[tuple[str, str]] = set()
    for candidate in (
        db.query(Candidate)
        .filter(
            Candidate.candidate_type == CANDIDATE_TYPE_RELATIONSHIP,
            Candidate.status.in_([CANDIDATE_STATUS_PENDING, CANDIDATE_STATUS_EDITED]),
        )
        .all()
    ):
        proposed = candidate.proposed_data or {}
        if proposed.get("relationship_type") != "POSSIBLE_MATCH":
            continue
        source = proposed.get("source_name")
        target = proposed.get("target_name")
        if source and target:
            pairs.add((normalize_name(source), normalize_name(target)))
    return names, pairs


def _dedupe_possible_matches(
    relationships: list[RelationshipCandidate],
) -> list[RelationshipCandidate]:
    """One POSSIBLE_MATCH candidate per (source, target) pair.

    Merges batch-internal matches (same document) with cross-document
    matches so a pair is never proposed twice.
    """
    seen: set[tuple[str, str]] = set()
    kept: list[RelationshipCandidate] = []
    for relationship in relationships:
        if relationship.relationship_type != "POSSIBLE_MATCH":
            kept.append(relationship)
            continue
        key = (
            normalize_name(relationship.source_name),
            normalize_name(relationship.target_name),
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(relationship)
    return kept


def get_candidate(db: Session, candidate_id: str) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFoundError("Candidate not found.")
    return candidate


def list_candidates(
    db: Session,
    *,
    status: str | None = None,
    candidate_type: str | None = None,
    document_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Candidate]:
    query = db.query(Candidate).order_by(Candidate.created_at.asc())
    if status:
        query = query.filter(Candidate.status == status)
    if candidate_type:
        query = query.filter(Candidate.candidate_type == candidate_type)
    if document_id:
        query = query.filter(Candidate.source_document_id == document_id)
    return query.offset(offset).limit(limit).all()


def update_candidate(
    db: Session,
    candidate: Candidate,
    *,
    proposed_data: dict,
    reason: str | None = None,
    user: str | None = None,
) -> Candidate:
    """Apply edits to a candidate's proposed data (status -> EDITED)."""
    if candidate.status not in ("PENDING", "EDITED"):
        raise CandidateStateError("Only pending or edited candidates can be modified.")
    previous = dict(candidate.proposed_data or {})
    incoming = dict(proposed_data)
    # Evidence references are internal bookkeeping, not reviewable edits —
    # preserve them when the reviewer does not touch them.
    refs = previous.get("evidence_refs")
    if refs is not None and "evidence_refs" not in incoming:
        incoming["evidence_refs"] = refs
    candidate.proposed_data = incoming
    candidate.status = CANDIDATE_STATUS_EDITED
    db.flush()
    log_action(
        db,
        action="UPDATE",
        object_type="candidate",
        object_id=candidate.candidate_id,
        previous_value=previous,
        new_value=proposed_data,
        reason=reason or "candidate edited",
        user=user,
    )
    return candidate


def reject_candidate(
    db: Session,
    candidate: Candidate,
    *,
    reviewed_by: str | None = None,
    reason: str | None = None,
) -> Candidate:
    """Reject a candidate: it stays in history but never enters trusted data."""
    from app.models.candidate import CANDIDATE_STATUS_REJECTED

    if candidate.status not in ("PENDING", "EDITED"):
        raise CandidateStateError("Candidate is not in a reviewable state.")
    candidate.status = CANDIDATE_STATUS_REJECTED
    candidate.reviewed_at = utcnow()
    candidate.reviewed_by = reviewed_by
    db.flush()
    log_action(
        db,
        action="REJECT",
        object_type="candidate",
        object_id=candidate.candidate_id,
        new_value={"status": CANDIDATE_STATUS_REJECTED},
        reason=reason or "rejected by reviewer",
        user=reviewed_by,
    )
    return candidate
