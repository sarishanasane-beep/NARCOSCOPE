"""Cross-case intelligence (Prompt 2 Part 2/3).

Identifies trusted entities appearing across multiple cases and detects
case overlap. The SAME canonical entity is never duplicated per case —
the database identity is the single source of truth. Case overlap is a
documented association, never proof of wrongdoing.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.entity import Entity
from app.models.event import Event
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
from app.utils.errors import NotFoundError


def _confirmed_case_links(db: Session, entity_id: str) -> list[dict[str, Any]]:
    """Confirmed relationships/facts tying an entity to cases."""
    links: list[dict[str, Any]] = []
    rels = (
        db.query(Relationship)
        .filter(
            Relationship.status == REL_STATUS_CONFIRMED,
            Relationship.case_id.isnot(None),
            or_(
                Relationship.source_entity_id == entity_id,
                Relationship.target_entity_id == entity_id,
            ),
        )
        .all()
    )
    for rel in rels:
        other_id = (
            rel.target_entity_id
            if rel.source_entity_id == entity_id
            else rel.source_entity_id
        )
        links.append(
            {
                "case_id": rel.case_id,
                "other_entity_id": other_id,
                "relationship_type": rel.relationship_type,
                "classification": rel.classification,
                "evidence_id": rel.evidence_id,
                "event_id": rel.event_id,
            }
        )
    facts = (
        db.query(Fact)
        .filter(
            Fact.status == FACT_STATUS_CONFIRMED,
            Fact.case_id.isnot(None),
            or_(
                Fact.subject_entity_id == entity_id,
                Fact.object_entity_id == entity_id,
            ),
        )
        .all()
    )
    for fact in facts:
        other_id = (
            fact.object_entity_id
            if fact.subject_entity_id == entity_id
            else fact.subject_entity_id
        )
        links.append(
            {
                "case_id": fact.case_id,
                "other_entity_id": other_id,
                "relationship_type": fact.predicate,
                "classification": "DIRECT",
                "evidence_id": fact.evidence_id,
                "event_id": fact.event_id,
            }
        )
    return links


def _entity_brief(db: Session, entity_id: str) -> dict[str, Any] | None:
    entity = db.get(Entity, entity_id)
    if entity is None:
        return None
    return {
        "entity_id": entity.entity_id,
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type,
        "status": entity.status,
    }


def entity_cases(db: Session, entity_id: str) -> list[dict[str, Any]]:
    """All trusted cases an entity is documented in, with the other
    entities, events and sources connected in each case."""
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("Entity not found.")
    links = _confirmed_case_links(db, entity_id)

    cases_by_id: dict[str, dict[str, Any]] = {}
    for link in links:
        case_id = link["case_id"]
        entry = cases_by_id.setdefault(
            case_id,
            {"case_id": case_id, "entities": {}, "events": {}, "evidence_ids": set()},
        )
        if link["other_entity_id"]:
            entry["entities"][link["other_entity_id"]] = {
                "entity_id": link["other_entity_id"],
                "relationship_type": link["relationship_type"],
                "classification": link["classification"],
                "evidence_id": link["evidence_id"],
            }
        if link["event_id"]:
            entry["events"].setdefault(
                link["event_id"], {"event_id": link["event_id"]}
            )
        if link["evidence_id"]:
            entry["evidence_ids"].add(link["evidence_id"])

    result: list[dict[str, Any]] = []
    for case_id, entry in cases_by_id.items():
        case = db.get(Case, case_id)
        if case is None:
            continue
        entities: list[dict[str, Any]] = []
        for other_id in entry["entities"]:
            brief = _entity_brief(db, other_id)
            if brief is not None:
                brief["relationship_type"] = entry["entities"][other_id]["relationship_type"]
                brief["classification"] = entry["entities"][other_id]["classification"]
                brief["evidence_id"] = entry["entities"][other_id]["evidence_id"]
                entities.append(brief)
        events: list[dict[str, Any]] = []
        for event_id in entry["events"]:
            event = db.get(Event, event_id)
            if event is not None:
                events.append(
                    {
                        "event_id": event.event_id,
                        "title": event.title,
                        "event_type": event.event_type,
                        "date_precision": event.date_precision,
                        "start_date": event.start_date.isoformat() if event.start_date else None,
                    }
                )
        result.append(
            {
                "case_id": case.case_id,
                "case_number": case.official_case_number,
                "case_name": case.case_name,
                "jurisdiction": case.jurisdiction,
                "status": case.status,
                "entities": sorted(entities, key=lambda e: e["canonical_name"]),
                "events": sorted(events, key=lambda e: e.get("start_date") or ""),
                "evidence_count": len(entry["evidence_ids"]),
            }
        )
    result.sort(key=lambda c: (c["case_number"] or "", c["case_name"] or ""))
    return result


def cross_case_connections(db: Session, entity_id: str) -> dict[str, Any]:
    """Documented investigation history across ALL trusted cases for one
    canonical entity (never one node per case)."""
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("Entity not found.")
    aliases: list[str] = []
    if entity.person is not None:
        aliases = list(entity.person.aliases or [])
    elif entity.organization is not None:
        aliases = list(entity.organization.aliases or [])
    cases = entity_cases(db, entity_id)
    return {
        "entity_id": entity.entity_id,
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type,
        "status": entity.status,
        "aliases": aliases,
        "case_count": len(cases),
        "cases": cases,
    }


def case_overlap(db: Session) -> list[dict[str, Any]]:
    """Detect trusted entities/events connecting multiple cases.

    Each entry pairs two cases and lists the shared entities/events with
    evidence references. Deterministic ordering (case numbers sorted).
    """
    case_entities: dict[str, set[str]] = {}
    case_events: dict[str, set[str]] = {}
    entity_case_evidence: dict[tuple[str, str], set[str]] = {}

    def _register(case_id: str, entity_id: str, evidence_id: str | None) -> None:
        case_entities.setdefault(case_id, set()).add(entity_id)
        if evidence_id:
            entity_case_evidence.setdefault((case_id, entity_id), set()).add(evidence_id)

    for rel in (
        db.query(Relationship)
        .filter(Relationship.status == REL_STATUS_CONFIRMED, Relationship.case_id.isnot(None))
        .all()
    ):
        _register(rel.case_id, rel.source_entity_id, rel.evidence_id)
        _register(rel.case_id, rel.target_entity_id, rel.evidence_id)
        if rel.event_id:
            case_events.setdefault(rel.case_id, set()).add(rel.event_id)
    for fact in (
        db.query(Fact)
        .filter(Fact.status == FACT_STATUS_CONFIRMED, Fact.case_id.isnot(None))
        .all()
    ):
        _register(fact.case_id, fact.subject_entity_id, fact.evidence_id)
        if fact.object_entity_id:
            _register(fact.case_id, fact.object_entity_id, fact.evidence_id)
        if fact.event_id:
            case_events.setdefault(fact.case_id, set()).add(fact.event_id)
    for event in db.query(Event).filter(Event.case_id.isnot(None)).all():
        case_events.setdefault(event.case_id, set()).add(event.event_id)

    case_order = sorted(case_entities, key=lambda c: c)
    overlaps: list[dict[str, Any]] = []
    for i, case_a in enumerate(case_order):
        for case_b in case_order[i + 1:]:
            shared_entities = case_entities[case_a] & case_entities[case_b]
            shared_events = case_events.get(case_a, set()) & case_events.get(case_b, set())
            if not shared_entities and not shared_events:
                continue
            entity_rows: list[dict[str, Any]] = []
            for entity_id in sorted(shared_entities):
                brief = _entity_brief(db, entity_id)
                if brief is None:
                    continue
                evidence_ids = (
                    entity_case_evidence.get((case_a, entity_id), set())
                    | entity_case_evidence.get((case_b, entity_id), set())
                )
                brief["evidence_ids"] = sorted(evidence_ids)
                entity_rows.append(brief)
            event_rows: list[dict[str, Any]] = []
            for event_id in sorted(shared_events):
                event = db.get(Event, event_id)
                if event is not None:
                    event_rows.append(
                        {
                            "event_id": event.event_id,
                            "title": event.title,
                            "event_type": event.event_type,
                        }
                    )
            case_a_row = db.get(Case, case_a)
            case_b_row = db.get(Case, case_b)
            if case_a_row is None or case_b_row is None:
                continue
            overlaps.append(
                {
                    "case_a": {
                        "case_id": case_a,
                        "case_number": case_a_row.official_case_number,
                        "case_name": case_a_row.case_name,
                    },
                    "case_b": {
                        "case_id": case_b,
                        "case_number": case_b_row.official_case_number,
                        "case_name": case_b_row.case_name,
                    },
                    "shared_entity_count": len(entity_rows),
                    "shared_entities": entity_rows,
                    "shared_event_count": len(event_rows),
                    "shared_events": event_rows,
                }
            )
    return overlaps
