"""Shared helpers for the Prompt 2 graph/intelligence tests.

Mirrors the helper style used by ``test_graph.py`` (Phase 1 Prompt 2
Part 1) so the new test files stay consistent with the existing suite.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.models.candidate import (
    CANDIDATE_STATUS_CONFIRMED,
    CANDIDATE_TYPE_EVENT,
    Candidate,
)
from app.models.case import Case
from app.models.document import Document
from app.models.entity import Entity
from app.models.evidence import Evidence
from app.models.event import Event
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.location import Location
from app.models.relationship import (
    CLASSIFICATION_DIRECT,
    REL_STATUS_CONFIRMED,
    Relationship,
)
from app.models.source import Source
from app.services.entities.resolution import create_entity


def person(db, name="Suresh Patil", aliases=None):
    return create_entity(db, entity_type="PERSON", canonical_name=name, aliases=aliases or [])


def org(db, name="Narcotics Control Bureau"):
    return create_entity(db, entity_type="ORGANIZATION", canonical_name=name)


def location(db, name="Mumbai"):
    return create_entity(db, entity_type="LOCATION", canonical_name=name)


def operation(db, name="Operation Bluewater"):
    return create_entity(db, entity_type="OTHER", canonical_name=name)


def case(db, number=None, name=None):
    case_row = Case(
        case_id=str(uuid.uuid4()),
        official_case_number=number,
        case_name=name,
        status="UNKNOWN",
    )
    db.add(case_row)
    db.flush()
    return case_row


def event(
    db,
    title="Operation Bluewater",
    event_type="OPERATION",
    precision="DAY",
    start=None,
    end=None,
    case_row=None,
    location_entity=None,
):
    event_row = Event(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        title=title,
        date_precision=precision,
        start_date=date.fromisoformat(start) if start else None,
        end_date=date.fromisoformat(end) if end else None,
        case_id=case_row.case_id if case_row else None,
        location_id=location_entity.location.location_id if location_entity else None,
    )
    db.add(event_row)
    db.flush()
    return event_row


def document(db, filename="report.txt", publication_date=None):
    doc = Document(
        document_id=str(uuid.uuid4()),
        filename=filename,
        stored_filename=filename,
        file_type="txt",
        mime_type="text/plain",
        file_size=10,
        sha256_hash="0" * 64,
        storage_path="/tmp/x.txt",
        processing_status="PROCESSED",
        publication_date=publication_date,
    )
    db.add(doc)
    db.flush()
    return doc


def source(
    db,
    publisher="Demo Press",
    agency="Demo Agency",
    source_type="SECONDARY_SOURCE",
    publication_date=None,
):
    src = Source(
        source_id=str(uuid.uuid4()),
        publisher=publisher,
        agency=agency,
        source_type=source_type,
        publication_date=publication_date,
    )
    db.add(src)
    db.flush()
    return src


def evidence(
    db,
    document,
    source=None,
    exact_text="Arjun Mehta was arrested during Operation Bluewater.",
):
    ev = Evidence(
        evidence_id=str(uuid.uuid4()),
        document_id=document.document_id,
        source_id=source.source_id if source else None,
        exact_text=exact_text,
        extraction_method="deterministic_rules",
        extraction_confidence=0.9,
    )
    db.add(ev)
    db.flush()
    return ev


def relationship(
    db,
    source_entity,
    target_entity,
    rtype,
    classification=CLASSIFICATION_DIRECT,
    status=REL_STATUS_CONFIRMED,
    confidence=0.9,
    evidence=None,
    case_row=None,
    event_row=None,
):
    rel = Relationship(
        relationship_id=str(uuid.uuid4()),
        source_entity_id=source_entity.entity_id,
        relationship_type=rtype,
        target_entity_id=target_entity.entity_id,
        classification=classification,
        status=status,
        confidence=confidence,
        evidence_id=evidence.evidence_id if evidence else None,
        case_id=case_row.case_id if case_row else None,
        event_id=event_row.event_id if event_row else None,
    )
    db.add(rel)
    db.flush()
    return rel


def confirmed_event_candidate(db, title, evidence=None):
    """Confirmed EVENT candidate (mirrors the seed flow) so the event's
    evidence chain can be resolved by provenance/timeline code."""
    cand = Candidate(
        candidate_id=str(uuid.uuid4()),
        candidate_type=CANDIDATE_TYPE_EVENT,
        proposed_data={
            "title": title,
            "event_type": "OPERATION",
            "date_precision": "DAY",
        },
        reason="test confirmed event candidate",
        status=CANDIDATE_STATUS_CONFIRMED,
        evidence_id=evidence.evidence_id if evidence else None,
    )
    db.add(cand)
    db.flush()
    return cand


def fact(
    db,
    subject,
    predicate,
    case_row=None,
    event_row=None,
    object_entity=None,
    evidence=None,
):
    fact_row = Fact(
        fact_id=str(uuid.uuid4()),
        subject_entity_id=subject.entity_id,
        predicate=predicate,
        object_entity_id=object_entity.entity_id if object_entity else None,
        case_id=case_row.case_id if case_row else None,
        event_id=event_row.event_id if event_row else None,
        evidence_id=evidence.evidence_id if evidence else None,
        status=FACT_STATUS_CONFIRMED,
        confidence=0.9,
    )
    db.add(fact_row)
    db.flush()
    return fact_row
