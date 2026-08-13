"""Provenance — explain why a trusted graph edge exists.

Resolves the chain:

    GRAPH EDGE -> TRUSTED RECORD -> CASE / EVENT / DOCUMENT
               -> EVIDENCE REFERENCE -> EXACT SOURCE TEXT

reusing the existing Evidence / Document / Source models. No parallel
evidence storage is created.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.candidate import (
    CANDIDATE_STATUS_CONFIRMED,
    CANDIDATE_TYPE_EVENT,
    Candidate,
)
from app.models.case import Case
from app.models.entity import Entity
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.fact import Fact
from app.models.location import Location
from app.models.relationship import Relationship
from app.utils.errors import NotFoundError


def _evidence_chain(db: Session, evidence_id: str | None) -> dict[str, Any] | None:
    """Evidence -> document -> source for one evidence record."""
    if not evidence_id:
        return None
    evidence = db.get(Evidence, evidence_id)
    if evidence is None:
        return None
    chain: dict[str, Any] = {
        "evidence": {
            "evidence_id": evidence.evidence_id,
            "exact_text": evidence.exact_text,
            "page_number": evidence.page_number,
            "extraction_method": evidence.extraction_method,
            "extraction_confidence": evidence.extraction_confidence,
        }
    }
    document = evidence.document
    if document is not None:
        chain["document"] = {
            "document_id": document.document_id,
            "filename": document.filename,
            "file_type": document.file_type,
            "publication_date": document.publication_date.isoformat()
            if document.publication_date
            else None,
            "upload_timestamp": document.upload_timestamp.isoformat()
            if document.upload_timestamp
            else None,
        }
    source = evidence.source
    if source is not None:
        chain["source"] = {
            "source_id": source.source_id,
            "publisher": source.publisher,
            "agency": source.agency,
            "source_type": source.source_type,
            "source_url": source.source_url,
            "publication_date": source.publication_date.isoformat()
            if source.publication_date
            else None,
        }
    return chain


def _event_evidence_chain(db: Session, event: Event) -> dict[str, Any] | None:
    """Evidence chain for a trusted event.

    Confirmed events carry ``evidence_id``/``document_id`` directly, so the
    chain resolves from the FK. For pre-existing events confirmed before
    those columns existed, the confirmed EVENT candidate is matched by
    title as a fallback.
    """
    if event.evidence_id:
        chain = _evidence_chain(db, event.evidence_id)
        if chain is not None:
            return chain
    if event.document_id:
        from app.models.document import Document

        document = db.get(Document, event.document_id)
        if document is not None:
            return _chain_for_document(db, document)
    for candidate in (
        db.query(Candidate)
        .filter(
            Candidate.candidate_type == CANDIDATE_TYPE_EVENT,
            Candidate.status == CANDIDATE_STATUS_CONFIRMED,
        )
        .all()
    ):
        if (candidate.proposed_data or {}).get("title") == event.title:
            chain = _evidence_chain(db, candidate.evidence_id)
            if chain is not None:
                return chain
    return None


def _chain_for_document(db: Session, document: Any) -> dict[str, Any] | None:
    """Document + source chain without an evidence snippet (used when only
    the event's source document is known)."""
    chain: dict[str, Any] = {"evidence": None, "document": None, "source": None}
    chain["document"] = {
        "document_id": document.document_id,
        "filename": document.filename,
        "file_type": document.file_type,
        "publication_date": document.publication_date.isoformat()
        if document.publication_date
        else None,
        "upload_timestamp": document.upload_timestamp.isoformat()
        if document.upload_timestamp
        else None,
    }
    if document.source is not None:
        source = document.source
        chain["source"] = {
            "source_id": source.source_id,
            "publisher": source.publisher,
            "agency": source.agency,
            "source_type": source.source_type,
            "source_url": source.source_url,
            "publication_date": source.publication_date.isoformat()
            if source.publication_date
            else None,
        }
    return chain


def event_source_publication_date(db: Session, event: Event) -> str | None:
    """Publication date of the source document that materialized an event
    (None when unresolvable). The event date itself is NEVER replaced by
    this value — callers keep the two concepts separate."""
    chain = _event_evidence_chain(db, event)
    if chain is None:
        return None
    if chain.get("document") and chain["document"].get("publication_date"):
        return chain["document"]["publication_date"]
    if chain.get("source") and chain["source"].get("publication_date"):
        return chain["source"]["publication_date"]
    return None


def edge_provenance(db: Session, edge_kind: str, edge_id: str) -> dict[str, Any]:
    """Resolve the provenance chain for one graph edge."""
    if edge_kind == "relationship":
        rel = db.get(Relationship, edge_id)
        if rel is None:
            raise NotFoundError("Relationship not found.")
        payload: dict[str, Any] = {
            "edge_kind": edge_kind,
            "edge_id": edge_id,
            "relationship_type": rel.relationship_type,
            "classification": rel.classification,
            "relationship": {
                "relationship_id": rel.relationship_id,
                "source_entity_id": rel.source_entity_id,
                "target_entity_id": rel.target_entity_id,
                "confidence": rel.confidence,
                "status": rel.status,
            },
            "evidence": None,
            "document": None,
            "source": None,
        }
        source_entity = db.get(Entity, rel.source_entity_id)
        target_entity = db.get(Entity, rel.target_entity_id)
        payload["source_name"] = source_entity.canonical_name if source_entity else None
        payload["source_type"] = source_entity.entity_type if source_entity else None
        payload["target_name"] = target_entity.canonical_name if target_entity else None
        payload["target_type"] = target_entity.entity_type if target_entity else None
        chain = _evidence_chain(db, rel.evidence_id)
        if chain:
            payload.update(chain)
        if rel.case_id:
            case = db.get(Case, rel.case_id)
            if case is not None:
                payload["case"] = {
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "official_case_number": case.official_case_number,
                }
        if rel.event_id:
            event = db.get(Event, rel.event_id)
            if event is not None:
                payload["event"] = {
                    "event_id": event.event_id,
                    "title": event.title,
                    "event_type": event.event_type,
                    "date_precision": event.date_precision,
                }
        return payload

    if edge_kind == "fact":
        fact = db.get(Fact, edge_id)
        if fact is None:
            raise NotFoundError("Fact not found.")
        payload = {
            "edge_kind": edge_kind,
            "edge_id": edge_id,
            "relationship_type": fact.predicate,
            "classification": "DIRECT",
            "fact": {
                "fact_id": fact.fact_id,
                "subject_entity_id": fact.subject_entity_id,
                "predicate": fact.predicate,
                "object_entity_id": fact.object_entity_id,
                "confidence": fact.confidence,
                "status": fact.status,
            },
            "evidence": None,
            "document": None,
            "source": None,
        }
        subject_entity = db.get(Entity, fact.subject_entity_id)
        payload["source_name"] = subject_entity.canonical_name if subject_entity else None
        payload["source_type"] = subject_entity.entity_type if subject_entity else None
        payload["target_name"] = None
        payload["target_type"] = None
        if fact.object_entity_id:
            object_entity = db.get(Entity, fact.object_entity_id)
            payload["target_name"] = object_entity.canonical_name if object_entity else None
            payload["target_type"] = object_entity.entity_type if object_entity else None
        chain = _evidence_chain(db, fact.evidence_id)
        if chain:
            payload.update(chain)
        if fact.case_id:
            case = db.get(Case, fact.case_id)
            if case is not None:
                payload["case"] = {
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "official_case_number": case.official_case_number,
                }
        return payload

    if edge_kind in ("event_case", "event_location"):
        event = db.get(Event, edge_id)
        if event is None:
            raise NotFoundError("Event not found.")
        relationship_type = "PART_OF" if edge_kind == "event_case" else "OCCURRED_IN"
        payload = {
            "edge_kind": edge_kind,
            "edge_id": edge_id,
            "relationship_type": relationship_type,
            "classification": "DIRECT",
            "event": {
                "event_id": event.event_id,
                "title": event.title,
                "event_type": event.event_type,
                "date_precision": event.date_precision,
                "start_date": event.start_date.isoformat() if event.start_date else None,
            },
            "evidence": None,
            "document": None,
            "source": None,
        }
        if edge_kind == "event_case" and event.case_id:
            case = db.get(Case, event.case_id)
            if case is not None:
                payload["case"] = {
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "official_case_number": case.official_case_number,
                }
        if edge_kind == "event_location" and event.location_id:
            location = db.get(Location, event.location_id)
            if location is not None:
                payload["location"] = {
                    "location_id": location.location_id,
                    "canonical_name": location.canonical_name,
                }
        chain = _event_evidence_chain(db, event)
        if chain:
            payload.update(chain)
        return payload

    if edge_kind == "location_parent":
        location = db.get(Location, edge_id)
        if location is None or location.parent_location_id is None:
            raise NotFoundError("Location parent not found.")
        parent = db.get(Location, location.parent_location_id)
        payload = {
            "edge_kind": edge_kind,
            "edge_id": edge_id,
            "relationship_type": "LOCATED_IN",
            "classification": "DIRECT",
            "location": {
                "location_id": location.location_id,
                "canonical_name": location.canonical_name,
            },
            "evidence": None,
            "document": None,
            "source": None,
        }
        if parent is not None:
            payload["parent"] = {
                "location_id": parent.location_id,
                "canonical_name": parent.canonical_name,
            }
        return payload

    raise NotFoundError("Unknown graph edge kind.")
