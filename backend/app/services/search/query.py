"""Reusable investigation query engine (Prompt 2 Part 2).

ONE global query service used by ``/search`` and saved-search re-runs —
never separate disconnected search implementations per page.

Filters: person / organization / case / case number / event / event type /
location / exact date / month / year / date range / relationship type /
source type / claim status.

DATE PRECISION RULE: results respect the stored precision. An event known
only as "June 2026" (MONTH) is never claimed to have happened on a
specific day; a query for exactly 15 June 2026 only matches DAY/RANGE
precision events whose window covers that day. MONTH/YEAR precision
events match month/year/range queries that intersect their window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.claim import Claim
from app.models.document import Document
from app.models.entity import Entity
from app.models.event import Event
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.location import Location
from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
from app.models.source import Source
from app.utils.errors import ValidationError

DATE_PRECISION_DAY = "DAY"
DATE_PRECISION_MONTH = "MONTH"
DATE_PRECISION_YEAR = "YEAR"
DATE_PRECISION_RANGE = "RANGE"
DATE_PRECISION_UNKNOWN = "UNKNOWN"

_EPOCH = date(1, 1, 1)
_FAR_FUTURE = date(9999, 12, 31)


@dataclass
class InvestigationQuery:
    """Structured investigation query (serializable for saved searches)."""

    q: str | None = None
    entity_type: str | None = None
    event_type: str | None = None
    location: str | None = None
    case_number: str | None = None
    relationship_type: str | None = None
    source_type: str | None = None
    claim_status: str | None = None
    date_from: str | None = None  # ISO YYYY-MM-DD
    date_to: str | None = None    # ISO YYYY-MM-DD
    limit: int = 20

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "InvestigationQuery":
        allowed = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in allowed})


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError(f"Invalid date filter '{value}'. Use YYYY-MM-DD.") from exc


def _month_end(day: date) -> date:
    if day.month == 12:
        return date(day.year, 12, 31)
    return date(day.year, day.month + 1, 1) - timedelta(days=1)


def event_window(event: Event) -> tuple[date, date] | None:
    """Known date window for an event, honoring precision.

    Returns (start, end) inclusive or None when the date is unknown.
    """
    if event.start_date is None or event.date_precision == DATE_PRECISION_UNKNOWN:
        return None
    if event.date_precision == DATE_PRECISION_RANGE:
        return (event.start_date, event.end_date or event.start_date)
    if event.date_precision == DATE_PRECISION_MONTH:
        return (event.start_date, _month_end(event.start_date))
    if event.date_precision == DATE_PRECISION_YEAR:
        return (event.start_date, date(event.start_date.year, 12, 31))
    return (event.start_date, event.start_date)


def window_overlaps(query_from: date, query_to: date, window: tuple[date, date] | None) -> bool:
    if window is None:
        return False
    return query_from <= window[1] and query_to >= window[0]


def _entity_out(entity: Entity) -> dict[str, Any]:
    aliases: list[str] = []
    if entity.person is not None:
        aliases = list(entity.person.aliases or [])
    elif entity.organization is not None:
        aliases = list(entity.organization.aliases or [])
    meta = entity.structured_metadata or {}
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type,
        "canonical_name": entity.canonical_name,
        "status": entity.status,
        "investigative_status": meta.get("investigative_status"),
        "mention_context": meta.get("mention_context"),
        "role": meta.get("role"),
        "aliases": aliases,
    }


def _event_out(event: Event) -> dict[str, Any]:
    location_name = None
    if event.location is not None:
        location_name = event.location.canonical_name
    case_number = None
    if event.case is not None:
        case_number = event.case.official_case_number or event.case.case_name
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "title": event.title,
        "date_precision": event.date_precision,
        "start_date": event.start_date.isoformat() if event.start_date else None,
        "end_date": event.end_date.isoformat() if event.end_date else None,
        "location": location_name,
        "case_id": event.case_id,
        "case_number": case_number,
    }


def run_query(db: Session, query: InvestigationQuery) -> dict[str, Any]:
    """Run a structured investigation query against the database."""
    limit = max(1, min(query.limit or 20, 200))
    name_pattern = f"%{(query.q or '').strip()}%"
    has_name = bool((query.q or "").strip())
    date_from = _parse_date(query.date_from)
    date_to = _parse_date(query.date_to)
    if date_from and date_to and date_from > date_to:
        raise ValidationError("date_from must not be after date_to.")
    query_from = date_from or _EPOCH
    query_to = date_to or _FAR_FUTURE

    # ------------------------------------------------------------------
    # Locations (for the location filter)
    # ------------------------------------------------------------------
    location_entity_ids: set[str] = set()
    location_names: set[str] = set()
    if query.location:
        location_rows = (
            db.query(Location)
            .join(Entity, Entity.entity_id == Location.entity_id)
            .filter(
                or_(
                    Location.canonical_name.ilike(f"%{query.location}%"),
                    Entity.canonical_name.ilike(f"%{query.location}%"),
                )
            )
            .all()
        )
        location_entity_ids = {row.entity_id for row in location_rows}
        location_names = {row.canonical_name for row in location_rows}

    # ------------------------------------------------------------------
    # Events (event type / location / case number / date filters)
    # ------------------------------------------------------------------
    event_query = db.query(Event)
    if query.event_type:
        event_query = event_query.filter(Event.event_type == query.event_type)
    events = event_query.all()
    if query.case_number:
        matching_case_ids = {
            c.case_id
            for c in db.query(Case)
            .filter(
                or_(
                    Case.official_case_number.ilike(f"%{query.case_number}%"),
                    Case.case_name.ilike(f"%{query.case_number}%"),
                )
            )
            .all()
        }
        events = [e for e in events if e.case_id in matching_case_ids]
    if location_entity_ids:
        events = [
            e for e in events
            if e.location_id is not None
            and e.location is not None
            and e.location.entity_id in location_entity_ids
        ]
    if date_from or date_to:
        if date_from and date_to and date_from == date_to:
            # EXACT-DAY QUERY: only DAY/RANGE precision events whose window
            # covers the day may match — a MONTH/YEAR precision event is
            # never claimed to have happened on a specific day.
            events = [
                e for e in events
                if e.date_precision in (DATE_PRECISION_DAY, DATE_PRECISION_RANGE)
                and window_overlaps(query_from, query_to, event_window(e))
            ]
        else:
            events = [
                e for e in events
                if window_overlaps(query_from, query_to, event_window(e))
            ]
    if has_name:
        needle = (query.q or "").strip().lower()
        # An event matches a free-text term when its title contains it OR
        # when a trusted (confirmed) entity whose name matches the term is
        # linked to the event through confirmed facts/relationships. This
        # keeps q in the TRUSTED domain — candidate data never influences
        # the query.
        matched_entity_ids = {
            e.entity_id
            for e in db.query(Entity).filter(Entity.canonical_name.ilike(name_pattern)).all()
        }
        linked_event_ids: set[str] = set()
        if matched_entity_ids:
            for rel in (
                db.query(Relationship)
                .filter(
                    Relationship.status == REL_STATUS_CONFIRMED,
                    Relationship.event_id.isnot(None),
                    or_(
                        Relationship.source_entity_id.in_(matched_entity_ids),
                        Relationship.target_entity_id.in_(matched_entity_ids),
                    ),
                )
                .all()
            ):
                linked_event_ids.add(rel.event_id)
            for fact in (
                db.query(Fact)
                .filter(
                    Fact.status == FACT_STATUS_CONFIRMED,
                    Fact.event_id.isnot(None),
                    or_(
                        Fact.subject_entity_id.in_(matched_entity_ids),
                        Fact.object_entity_id.in_(matched_entity_ids),
                    ),
                )
                .all()
            ):
                linked_event_ids.add(fact.event_id)
        events = [
            e for e in events
            if needle in (e.title or "").lower() or e.event_id in linked_event_ids
        ]
    events = events[:limit]
    event_ids = {e.event_id for e in events}

    # ------------------------------------------------------------------
    # Entities linked to filtered events (for location/date/type filters)
    # ------------------------------------------------------------------
    linked_entity_ids: set[str] = set()
    if event_ids:
        for rel in (
            db.query(Relationship)
            .filter(
                Relationship.status == REL_STATUS_CONFIRMED,
                Relationship.event_id.in_(event_ids),
            )
            .all()
        ):
            linked_entity_ids.add(rel.source_entity_id)
            linked_entity_ids.add(rel.target_entity_id)
        for fact in (
            db.query(Fact)
            .filter(
                Fact.status == FACT_STATUS_CONFIRMED,
                Fact.event_id.in_(event_ids),
            )
            .all()
        ):
            linked_entity_ids.add(fact.subject_entity_id)
            if fact.object_entity_id:
                linked_entity_ids.add(fact.object_entity_id)

    if query.relationship_type:
        type_linked: set[str] = set()
        for rel in (
            db.query(Relationship)
            .filter(
                Relationship.status == REL_STATUS_CONFIRMED,
                Relationship.relationship_type == query.relationship_type,
            )
            .all()
        ):
            type_linked.add(rel.source_entity_id)
            type_linked.add(rel.target_entity_id)
        linked_entity_ids = linked_entity_ids & type_linked if linked_entity_ids else type_linked

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------
    entity_query = db.query(Entity)
    if linked_entity_ids:
        entity_query = entity_query.filter(Entity.entity_id.in_(linked_entity_ids))
    if query.entity_type:
        entity_query = entity_query.filter(Entity.entity_type == query.entity_type)
    if has_name:
        entity_query = entity_query.filter(Entity.canonical_name.ilike(name_pattern))
    entities = entity_query.order_by(Entity.canonical_name).limit(limit).all()
    if query.location and location_entity_ids:
        # Always surface the matched locations themselves.
        location_entities = (
            db.query(Entity)
            .filter(Entity.entity_id.in_(location_entity_ids))
            .all()
        )
        known = {e.entity_id for e in entities}
        entities = list(entities) + [e for e in location_entities if e.entity_id not in known]

    # ------------------------------------------------------------------
    # Cases
    # ------------------------------------------------------------------
    case_query = db.query(Case)
    if query.case_number:
        case_query = case_query.filter(
            or_(
                Case.official_case_number.ilike(f"%{query.case_number}%"),
                Case.case_name.ilike(f"%{query.case_number}%"),
            )
        )
    elif has_name:
        case_query = case_query.filter(
            or_(
                Case.case_name.ilike(name_pattern),
                Case.official_case_number.ilike(name_pattern),
                Case.operation_name.ilike(name_pattern),
            )
        )
    cases = case_query.all()
    if location_names:
        location_lower = {n.lower() for n in location_names}
        cases = [
            c for c in cases
            if any(loc in (c.jurisdiction or "").lower() for loc in location_lower)
            or c.case_id in {e.case_id for e in events if e.case_id}
        ]
    if date_from or date_to:
        cases = [
            c for c in cases
            if c.start_date is not None
            and query_from <= c.start_date <= query_to
        ]
    cases = cases[:limit]

    # ------------------------------------------------------------------
    # Documents (source type / publication date filters)
    # ------------------------------------------------------------------
    doc_query = db.query(Document)
    if has_name:
        doc_query = doc_query.filter(Document.filename.ilike(name_pattern))
    documents = doc_query.all()
    if query.source_type:
        source_ids = {
            s.source_id
            for s in db.query(Source).filter(Source.source_type == query.source_type).all()
        }
        documents = [d for d in documents if d.source_id in source_ids]
    if date_from or date_to:
        documents = [
            d for d in documents
            if d.publication_date is not None
            and query_from <= d.publication_date <= query_to
        ]
    documents = documents[:limit]

    # ------------------------------------------------------------------
    # Claims (status filter only)
    # ------------------------------------------------------------------
    claims: list[dict[str, Any]] = []
    if query.claim_status:
        for claim in (
            db.query(Claim)
            .filter(Claim.claim_status == query.claim_status)
            .limit(limit)
            .all()
        ):
            claims.append(
                {
                    "claim_id": claim.claim_id,
                    "claim_text": claim.claim_text,
                    "claim_status": claim.claim_status,
                    "subject_entity_id": claim.subject_entity_id,
                }
            )

    entity_rows = [_entity_out(e) for e in entities]
    people = [r for r in entity_rows if r["entity_type"] == "PERSON"]
    organizations = [
        r for r in entity_rows if r["entity_type"] in ("ORGANIZATION", "AGENCY")
    ]
    locations = [r for r in entity_rows if r["entity_type"] == "LOCATION"]
    return {
        "query": query.as_dict(),
        "entities": entity_rows,
        "people": people,
        "organizations": organizations,
        "locations": locations,
        "cases": [
            {
                "case_id": c.case_id,
                "official_case_number": c.official_case_number,
                "case_name": c.case_name,
                "status": c.status,
                "jurisdiction": c.jurisdiction,
                "start_date": c.start_date.isoformat() if c.start_date else None,
            }
            for c in cases
        ],
        "events": [_event_out(e) for e in events],
        "documents": [
            {
                "document_id": d.document_id,
                "filename": d.filename,
                "processing_status": d.processing_status,
                "publication_date": d.publication_date.isoformat()
                if d.publication_date
                else None,
            }
            for d in documents
        ],
        "claims": claims,
        "meta": {
            "limit": limit,
            "location_matched": sorted(location_names),
        },
    }
