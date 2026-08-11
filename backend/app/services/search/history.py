"""Entity investigation history (Prompt 2 Part 2).

``entity_history`` builds a neutral, evidence-based view called
DOCUMENTED INVESTIGATION HISTORY — never "Criminal History". It spans
ALL trusted cases (not just the currently selected document), reuses the
existing trusted tables, and never implies guilt from graph proximity.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.entity import Entity
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
from app.models.source import Source
from app.utils.errors import NotFoundError


def entity_history(db: Session, entity_id: str) -> dict[str, Any]:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("Entity not found.")

    aliases: list[str] = []
    if entity.person is not None:
        aliases = list(entity.person.aliases or [])
    elif entity.organization is not None:
        aliases = list(entity.organization.aliases or [])

    rels = (
        db.query(Relationship)
        .filter(
            Relationship.status == REL_STATUS_CONFIRMED,
            (Relationship.source_entity_id == entity_id)
            | (Relationship.target_entity_id == entity_id),
        )
        .all()
    )
    facts = (
        db.query(Fact)
        .filter(
            Fact.status == FACT_STATUS_CONFIRMED,
            (Fact.subject_entity_id == entity_id)
            | (Fact.object_entity_id == entity_id),
        )
        .all()
    )

    case_ids = {r.case_id for r in rels if r.case_id} | {
        f.case_id for f in facts if f.case_id
    }
    event_ids = {r.event_id for r in rels if r.event_id} | {
        f.event_id for f in facts if f.event_id
    }
    other_entity_ids = {
        r.target_entity_id if r.source_entity_id == entity_id else r.source_entity_id
        for r in rels
    } | {
        f.object_entity_id if f.subject_entity_id == entity_id else f.subject_entity_id
        for f in facts
        if (f.object_entity_id if f.subject_entity_id == entity_id else f.subject_entity_id)
    }
    other_entity_ids.discard(None)
    other_entity_ids.discard(entity_id)

    cases = (
        db.query(Case).filter(Case.case_id.in_(case_ids)).all()
        if case_ids
        else []
    )
    events = (
        db.query(Event).filter(Event.event_id.in_(event_ids)).all()
        if event_ids
        else []
    )
    others = (
        db.query(Entity).filter(Entity.entity_id.in_(other_entity_ids)).all()
        if other_entity_ids
        else []
    )

    evidence_ids = {r.evidence_id for r in rels if r.evidence_id} | {
        f.evidence_id for f in facts if f.evidence_id
    }
    evidence_ids.discard(None)
    source_ids: set[str] = set()
    for evidence in (db.get(Evidence, eid) for eid in evidence_ids):
        if evidence is not None and evidence.source_id:
            source_ids.add(evidence.source_id)
    sources = db.query(Source).filter(Source.source_id.in_(source_ids)).all() if source_ids else []

    return {
        "entity": {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "status": entity.status,
            "aliases": aliases,
        },
        "documented_investigation_history": True,
        "case_count": len(cases),
        "cases": [
            {
                "case_id": c.case_id,
                "official_case_number": c.official_case_number,
                "case_name": c.case_name,
                "jurisdiction": c.jurisdiction,
                "status": c.status,
                "start_date": c.start_date.isoformat() if c.start_date else None,
            }
            for c in sorted(cases, key=lambda c: (c.official_case_number or "", c.case_name or ""))
        ],
        "events": [
            {
                "event_id": e.event_id,
                "title": e.title,
                "event_type": e.event_type,
                "date_precision": e.date_precision,
                "start_date": e.start_date.isoformat() if e.start_date else None,
                "case_id": e.case_id,
            }
            for e in sorted(events, key=lambda e: e.start_date or date.max)
        ],
        "organizations": [
            {
                "entity_id": o.entity_id,
                "canonical_name": o.canonical_name,
                "entity_type": o.entity_type,
            }
            for o in others
            if o.entity_type in ("ORGANIZATION", "AGENCY")
        ],
        "people": [
            {
                "entity_id": o.entity_id,
                "canonical_name": o.canonical_name,
                "entity_type": o.entity_type,
            }
            for o in others
            if o.entity_type == "PERSON"
        ],
        "locations": [
            {
                "entity_id": o.entity_id,
                "canonical_name": o.canonical_name,
                "entity_type": o.entity_type,
            }
            for o in others
            if o.entity_type == "LOCATION"
        ],
        "relationships": [
            {
                "source_entity_id": r.source_entity_id,
                "relationship_type": r.relationship_type,
                "target_entity_id": r.target_entity_id,
                "classification": r.classification,
                "status": r.status,
                "confidence": r.confidence,
                "case_id": r.case_id,
                "event_id": r.event_id,
                "evidence_id": r.evidence_id,
            }
            for r in rels
        ],
        "facts": [
            {
                "fact_id": f.fact_id,
                "subject_entity_id": f.subject_entity_id,
                "predicate": f.predicate,
                "object_entity_id": f.object_entity_id,
                "case_id": f.case_id,
                "event_id": f.event_id,
                "evidence_id": f.evidence_id,
            }
            for f in facts
        ],
        "sources": [
            {
                "source_id": s.source_id,
                "publisher": s.publisher,
                "agency": s.agency,
                "source_type": s.source_type,
                "publication_date": s.publication_date.isoformat()
                if s.publication_date
                else None,
            }
            for s in sorted(sources, key=lambda s: s.publisher or "")
        ],
    }
