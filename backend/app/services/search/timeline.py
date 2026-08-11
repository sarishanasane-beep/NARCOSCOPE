"""Timeline engine (Prompt 2 Part 2).

Reusable timeline functionality: global, case and entity timelines.

Each entry preserves BOTH concepts separately:
  - ``date`` / ``date_precision`` — the EVENT date (or case record date)
  - ``source_publication_date`` — when the supporting document was published

The event date is never replaced with the publication date. Unknown
precision is reported as UNKNOWN; a MONTH-precision event never renders
as an exact day.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.entity import Entity
from app.models.event import Event
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
from app.services.graph.provenance import event_source_publication_date
from app.utils.errors import NotFoundError


def _event_entry(db: Session, event: Event) -> dict[str, Any]:
    location_name = None
    if event.location is not None:
        location_name = event.location.canonical_name
    case_number = None
    if event.case is not None:
        case_number = event.case.official_case_number or event.case.case_name
    return {
        "kind": "event",
        "date": event.start_date.isoformat() if event.start_date else None,
        "date_precision": event.date_precision,
        "source_publication_date": event_source_publication_date(db, event),
        "title": event.title,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "location": location_name,
        "case_id": event.case_id,
        "case_number": case_number,
    }


def _case_entry(case: Case) -> dict[str, Any]:
    return {
        "kind": "case",
        "date": case.start_date.isoformat() if case.start_date else None,
        # The case record stores an exact date — this is the recorded value,
        # not an inference.
        "date_precision": "DAY" if case.start_date else "UNKNOWN",
        "source_publication_date": None,
        "title": case.case_name or case.official_case_number or case.case_id,
        "case_id": case.case_id,
        "case_number": case.official_case_number,
        "jurisdiction": case.jurisdiction,
    }


def _sorted_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _sort_key(entry: dict[str, Any]) -> tuple:
        return (entry.get("date") or "9999-12-31", entry.get("kind", ""))
    return sorted(entries, key=_sort_key)


def global_timeline(
    db: Session,
    event_type: str | None = None,
    location: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """Chronological trusted timeline (events + case records)."""
    from app.services.search.query import _parse_date, event_window, window_overlaps

    events = db.query(Event).order_by(Event.start_date).all()
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    if location:
        events = [
            e for e in events
            if e.location is not None
            and location.lower() in (e.location.canonical_name or "").lower()
        ]
    q_from = _parse_date(date_from)
    q_to = _parse_date(date_to)
    if q_from or q_to:
        from app.services.search.query import (
            DATE_PRECISION_DAY,
            DATE_PRECISION_RANGE,
            _EPOCH,
            _FAR_FUTURE,
        )

        lo = q_from or _EPOCH
        hi = q_to or _FAR_FUTURE
        exact_day = q_from is not None and q_to is not None and q_from == q_to
        if exact_day:
            events = [
                e for e in events
                if e.date_precision in (DATE_PRECISION_DAY, DATE_PRECISION_RANGE)
                and window_overlaps(lo, hi, event_window(e))
            ]
        else:
            events = [e for e in events if window_overlaps(lo, hi, event_window(e))]

    entries: list[dict[str, Any]] = [_event_entry(db, e) for e in events]
    if not event_type and not location and not q_from and not q_to:
        cases = db.query(Case).filter(Case.start_date.isnot(None)).all()
        entries.extend(_case_entry(c) for c in cases)
    return _sorted_entries(entries)


def case_timeline(db: Session, case_id: str) -> list[dict[str, Any]]:
    """Chronological events of one case, with the case entry itself."""
    case = db.get(Case, case_id)
    if case is None:
        raise NotFoundError("Case not found.")
    events = db.query(Event).filter(Event.case_id == case_id).all()
    entries = [_event_entry(db, e) for e in events]
    entries.append(_case_entry(case))
    return _sorted_entries(entries)


def entity_timeline(db: Session, entity_id: str) -> list[dict[str, Any]]:
    """Person/organization/location history timeline spanning all trusted
    cases (events the entity participates in + case records)."""
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("Entity not found.")

    event_ids: set[str] = set()
    case_ids: set[str] = set()
    for rel in (
        db.query(Relationship)
        .filter(
            Relationship.status == REL_STATUS_CONFIRMED,
            (Relationship.source_entity_id == entity_id)
            | (Relationship.target_entity_id == entity_id),
        )
        .all()
    ):
        if rel.event_id:
            event_ids.add(rel.event_id)
        if rel.case_id:
            case_ids.add(rel.case_id)
    for fact in (
        db.query(Fact)
        .filter(
            Fact.status == FACT_STATUS_CONFIRMED,
            (Fact.subject_entity_id == entity_id)
            | (Fact.object_entity_id == entity_id),
        )
        .all()
    ):
        if fact.event_id:
            event_ids.add(fact.event_id)
        if fact.case_id:
            case_ids.add(fact.case_id)

    events = (
        db.query(Event).filter(Event.event_id.in_(event_ids)).all()
        if event_ids
        else []
    )
    if case_ids:
        for event in db.query(Event).filter(Event.case_id.in_(case_ids)).all():
            events.append(event)
    # dedupe preserving identity
    seen: set[str] = set()
    unique_events: list[Event] = []
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        unique_events.append(event)

    entries = [_event_entry(db, e) for e in unique_events]
    cases = (
        db.query(Case).filter(Case.case_id.in_(case_ids)).all()
        if case_ids
        else []
    )
    entries.extend(_case_entry(c) for c in cases if c.start_date is not None)
    return _sorted_entries(entries)
