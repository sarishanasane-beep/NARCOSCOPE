"""Search across trusted data (Prompt 2 Part 2).

With no filters this is the original substring search (entities, cases,
events, documents) — fully backward compatible. When any structured
filter is supplied (entity type, event type, location, case number,
relationship type, source type, claim status, date range) the query is
delegated to the ONE reusable query engine (``app.services.search.query``)
so every page uses the same service.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.document import Document
from app.models.entity import Entity
from app.models.event import Event
from app.services.search.query import InvestigationQuery, run_query


def _basic_search(db: Session, query: str, limit: int = 20) -> dict:
    q = f"%{query.strip()}%"

    entities = (
        db.query(Entity)
        .filter(or_(Entity.canonical_name.ilike(q)))
        .order_by(Entity.canonical_name)
        .limit(limit)
        .all()
    )
    cases = (
        db.query(Case)
        .filter(
            or_(
                Case.case_name.ilike(q),
                Case.official_case_number.ilike(q),
                Case.operation_name.ilike(q),
            )
        )
        .limit(limit)
        .all()
    )
    events = (
        db.query(Event)
        .filter(or_(Event.title.ilike(q)))
        .order_by(Event.start_date.desc())
        .limit(limit)
        .all()
    )
    documents = (
        db.query(Document)
        .filter(or_(Document.filename.ilike(q)))
        .order_by(Document.upload_timestamp.desc())
        .limit(limit)
        .all()
    )

    return {
        "entities": [
            {
                "entity_id": e.entity_id,
                "entity_type": e.entity_type,
                "canonical_name": e.canonical_name,
                "status": e.status,
                "aliases": (
                    list(e.person.aliases or [])
                    if e.person is not None
                    else list(e.organization.aliases or [])
                    if e.organization is not None
                    else []
                ),
            }
            for e in entities
        ],
        "cases": [
            {
                "case_id": c.case_id,
                "official_case_number": c.official_case_number,
                "case_name": c.case_name,
                "status": c.status,
            }
            for c in cases
        ],
        "events": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "title": e.title,
                "date_precision": e.date_precision,
            }
            for e in events
        ],
        "documents": [
            {
                "document_id": d.document_id,
                "filename": d.filename,
                "processing_status": d.processing_status,
            }
            for d in documents
        ],
        "people": [
            e for e in _entity_rows(entities) if e["entity_type"] == "PERSON"
        ],
        "organizations": [
            e for e in _entity_rows(entities)
            if e["entity_type"] in ("ORGANIZATION", "AGENCY")
        ],
        "locations": [
            e for e in _entity_rows(entities) if e["entity_type"] == "LOCATION"
        ],
        "claims": [],
    }


def _entity_rows(entities) -> list[dict[str, Any]]:
    return [
        {
            "entity_id": e.entity_id,
            "entity_type": e.entity_type,
            "canonical_name": e.canonical_name,
            "status": e.status,
            "aliases": (
                list(e.person.aliases or [])
                if e.person is not None
                else list(e.organization.aliases or [])
                if e.organization is not None
                else []
            ),
        }
        for e in entities
    ]


def search(
    db: Session,
    query: str,
    limit: int = 20,
    *,
    entity_type: str | None = None,
    event_type: str | None = None,
    location: str | None = None,
    case_number: str | None = None,
    relationship_type: str | None = None,
    source_type: str | None = None,
    claim_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    filters = {
        "entity_type": entity_type,
        "event_type": event_type,
        "location": location,
        "case_number": case_number,
        "relationship_type": relationship_type,
        "source_type": source_type,
        "claim_status": claim_status,
        "date_from": date_from,
        "date_to": date_to,
    }
    if not any(v for v in filters.values()):
        return _basic_search(db, query, limit=limit)
    structured = InvestigationQuery(q=query, limit=limit, **filters)
    return run_query(db, structured)
