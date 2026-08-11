"""Investigation workspaces (Prompt 2 Part 3 + Part 4).

A workspace collects pinned entities/cases/events/locations/relationships
for an investigation. Pins are lightweight references (kind + id + name)
— the workspace never copies database records, so it always reflects the
current trusted data.

Prompt 2 Part 4 adds the FINAL INVESTIGATION WORKSPACE: an aggregated
overview per workspace that combines the pinned subjects (resolved to
current trusted data), the changes relevant to those pins, investigation
priority for pinned entities, saved searches, and investigator notes.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.bookmark import Bookmark
from app.models.case import Case
from app.models.entity import Entity
from app.models.event import Event
from app.models.graph_change import GraphChange
from app.models.investigator_note import InvestigatorNote
from app.models.location import Location
from app.models.relationship import Relationship
from app.models.saved_search import SavedSearch
from app.models.workspace import Workspace
from app.services.graph.model import (
    case_node_id,
    entity_node_id,
    event_node_id,
)
from app.utils.errors import NotFoundError, ValidationError

PIN_KINDS = ("entity", "case", "event", "location", "relationship", "change")

_PIN_MODELS = {
    "entity": Entity,
    "case": Case,
    "event": Event,
    "location": Location,
    "relationship": Relationship,
}


# The attribute used to key each pin kind — the canonical identifier the
# rest of NARCOSCOPE uses for that record. Locations are keyed by
# ``location_id`` (the Location primary key) everywhere else in the
# codebase (graph builder, /graph/location/{location_id}, event
# ``location_id`` FK, GET /entities/locations/{location_id}) — NOT the
# entity id. ``_PIN_KEY_ATTR`` maps kind -> the key attribute name.
_PIN_KEY_ATTR: dict[str, str] = {
    "entity": "entity_id",
    "case": "case_id",
    "event": "event_id",
    "location": "location_id",
    "relationship": "relationship_id",
}


def _pin_key(kind: str, subject_id: str) -> tuple[str, str]:
    """Normalize a pin subject to (attribute, value) for its model."""
    return _PIN_KEY_ATTR.get(kind, ""), subject_id


def _validate_pin(db: Session, kind: str, subject_id: str) -> None:
    if kind not in PIN_KINDS:
        raise ValidationError(f"Unsupported pin kind '{kind}'.")
    model = _PIN_MODELS.get(kind)
    if model is None:
        return
    attr, value = _pin_key(kind, subject_id)
    row = (
        db.query(model).filter(getattr(model, attr) == value).first()
        if attr
        else db.get(model, subject_id)
    )
    if row is None:
        raise ValidationError(f"{kind.capitalize()} not found.")


def get_workspace(db: Session, workspace_id: str) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("Workspace not found.")
    return workspace


def list_workspaces(db: Session) -> list[Workspace]:
    return db.query(Workspace).order_by(Workspace.created_at.desc()).all()


def create_workspace(
    db: Session, name: str, description: str | None = None, created_by: str | None = None
) -> Workspace:
    if not name or not name.strip():
        raise ValidationError("Workspace name is required.")
    workspace = Workspace(
        workspace_id=str(uuid.uuid4()),
        name=name.strip(),
        description=description,
        created_by=created_by,
    )
    db.add(workspace)
    db.commit()
    return workspace


def update_workspace(
    db: Session, workspace_id: str, name: str | None = None, description: str | None = None
) -> Workspace:
    workspace = get_workspace(db, workspace_id)
    if name is not None:
        if not name.strip():
            raise ValidationError("Workspace name cannot be empty.")
        workspace.name = name.strip()
    if description is not None:
        workspace.description = description
    db.commit()
    return workspace


def delete_workspace(db: Session, workspace_id: str) -> None:
    workspace = get_workspace(db, workspace_id)
    db.delete(workspace)
    db.commit()


def add_pin(
    db: Session,
    workspace_id: str,
    kind: str,
    subject_id: str,
    name: str | None = None,
) -> Workspace:
    """Add a pin (idempotent: duplicate pins are ignored)."""
    workspace = get_workspace(db, workspace_id)
    _validate_pin(db, kind, subject_id)
    pins = list(workspace.pins or [])
    if any(p.get("kind") == kind and p.get("id") == subject_id for p in pins):
        return workspace
    pins.append({"kind": kind, "id": subject_id, "name": name})
    # Reassign a NEW list — in-place mutation of the JSON column is not
    # reliably persisted (regression rule from Prompt 1).
    workspace.pins = pins
    db.commit()
    return workspace


def remove_pin(db: Session, workspace_id: str, index: int) -> Workspace:
    workspace = get_workspace(db, workspace_id)
    pins = list(workspace.pins or [])
    if not 0 <= index < len(pins):
        raise ValidationError("Pin index out of range.")
    pins.pop(index)
    workspace.pins = pins
    db.commit()
    return workspace


def workspace_out(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace_id": workspace.workspace_id,
        "name": workspace.name,
        "description": workspace.description,
        "pins": list(workspace.pins or []),
        "created_by": workspace.created_by,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Prompt 2 Part 4 — final investigation workspace overview
# ---------------------------------------------------------------------------

# Display name attribute per pin kind (only used to build the default
# pin name when the pin was stored without one).
_PIN_DISPLAY: dict[str, str] = {
    "entity": "canonical_name",
    "case": "case_name",
    "event": "title",
    "location": "canonical_name",
    "relationship": "relationship_type",
}

_PIN_TYPES: dict[str, str] = {
    "entity": "ENTITY",
    "case": "CASE",
    "event": "EVENT",
    "location": "LOCATION",
    "relationship": "RELATIONSHIP",
}


def _resolve_pins(db: Session, workspace: Workspace) -> list[dict[str, Any]]:
    """Resolve each pin to its CURRENT trusted record (name + type).

    Pins that no longer resolve (record deleted) are still listed with
    the stored name and ``exists=False`` — the investigator keeps seeing
    the pin and can remove it. No data is copied into the workspace.
    """
    resolved: list[dict[str, Any]] = []
    for pin in workspace.pins or []:
        kind = pin.get("kind")
        subject_id = pin.get("id")
        model = _PIN_MODELS.get(kind)
        row = None
        if model is not None:
            attr, value = _pin_key(kind, subject_id)
            row = (
                db.query(model).filter(getattr(model, attr) == value).first()
                if attr
                else db.get(model, subject_id)
            )
        name = pin.get("name")
        if row is not None:
            name = getattr(row, _PIN_DISPLAY.get(kind, ""), None) or name
        item: dict[str, Any] = {
            "kind": kind,
            "id": subject_id,
            "name": name,
            "type": _PIN_TYPES.get(kind, "OTHER"),
            "exists": row is not None,
        }
        # Locations are keyed by location_id; expose the underlying
        # entity_id too so callers can resolve the graph/entity record.
        if row is not None and kind == "location":
            item["entity_id"] = row.entity_id
        resolved.append(item)
    return resolved


def _pin_entity_ids(pins: list[dict[str, Any]]) -> set[str]:
    return {p["id"] for p in pins if p["kind"] == "entity"}


def _pin_case_ids(pins: list[dict[str, Any]]) -> set[str]:
    return {p["id"] for p in pins if p["kind"] == "case"}


def _pin_event_ids(pins: list[dict[str, Any]]) -> set[str]:
    return {p["id"] for p in pins if p["kind"] == "event"}


def _change_matches(
    change: GraphChange, entity_ids: set[str], case_ids: set[str], event_ids: set[str]
) -> bool:
    """Does this detected change concern any pinned subject?

    Matches on the graph node/edge reference id stored in the change plus
    the entity/case/event ids recorded in its details. Aggregate changes
    (NETWORK_GROWTH) have no single subject and are always included.
    """
    if not entity_ids and not case_ids and not event_ids:
        return True
    if change.category == "NETWORK_GROWTH":
        return True
    ref = change.reference_id or ""
    if any(entity_node_id(e) == ref for e in entity_ids):
        return True
    if any(case_node_id(c) == ref for c in case_ids):
        return True
    if any(event_node_id(e) == ref for e in event_ids):
        return True
    details = change.details or {}
    for entity_id in entity_ids:
        if details.get("source") == entity_node_id(entity_id):
            return True
        if details.get("target") == entity_node_id(entity_id):
            return True
        if details.get("id") == entity_node_id(entity_id):
            return True
    for case_id in case_ids:
        if details.get("case_id") == case_id:
            return True
    for event_id in event_ids:
        if details.get("event_id") == event_id:
            return True
    return False


def _change_out(row: GraphChange) -> dict[str, Any]:
    return {
        "change_id": row.change_id,
        "snapshot_id": row.snapshot_id,
        "category": row.category,
        "significance": row.significance,
        "kind": row.kind,
        "reference_id": row.reference_id,
        "details": row.details or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _workspace_notes(db: Session, workspace_id: str) -> list[dict[str, Any]]:
    notes = (
        db.query(InvestigatorNote)
        .filter(InvestigatorNote.subject_kind == "workspace",
                InvestigatorNote.subject_id == workspace_id)
        .order_by(InvestigatorNote.created_at.desc())
        .all()
    )
    return [
        {
            "note_id": n.note_id,
            "subject_kind": n.subject_kind,
            "subject_id": n.subject_id,
            "content": n.content,
            "created_by": n.created_by,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
        }
        for n in notes
    ]


def workspace_overview(db: Session, workspace_id: str) -> dict[str, Any]:
    """Final investigation workspace: aggregated overview.

    Combines the workspace with its pinned subjects (resolved against the
    current trusted database), detected changes relevant to those pins,
    Investigation Priority for pinned entities, saved searches and
    workspace notes. Every input comes from the trusted/annotation stores
    — candidate data never enters the overview.
    """
    workspace = get_workspace(db, workspace_id)
    pins = _resolve_pins(db, workspace)
    entity_ids = _pin_entity_ids(pins)
    case_ids = _pin_case_ids(pins)
    event_ids = _pin_event_ids(pins)

    changes_rows = db.query(GraphChange).order_by(GraphChange.created_at.desc()).limit(500).all()
    changes = [
        _change_out(c)
        for c in changes_rows
        if _change_matches(c, entity_ids, case_ids, event_ids)
    ]

    from app.services.graph.priority import priority_for_entity

    priorities: list[dict[str, Any]] = []
    for entity_id in sorted(entity_ids):
        try:
            priority = priority_for_entity(db, entity_id)
        except NotFoundError:
            continue
        priorities.append(
            {
                "entity_id": entity_id,
                "total": priority["total"],
                "breakdown": priority["breakdown"],
                "disclaimer": priority["disclaimer"],
            }
        )
    # Include location pins' underlying entity ids in the priority set.
    for pin in pins:
        if pin["kind"] == "location" and pin["exists"] and pin.get("entity_id"):
            entity_id = pin["entity_id"]
            try:
                priority = priority_for_entity(db, entity_id)
            except NotFoundError:
                continue
            if not any(p["entity_id"] == entity_id for p in priorities):
                priorities.append(
                    {
                        "entity_id": entity_id,
                        "total": priority["total"],
                        "breakdown": priority["breakdown"],
                        "disclaimer": priority["disclaimer"],
                    }
                )
    priorities.sort(key=lambda p: (p["total"], p["entity_id"]), reverse=True)

    saved_searches = db.query(SavedSearch).order_by(SavedSearch.created_at.desc()).all()
    bookmarks = db.query(Bookmark).order_by(Bookmark.created_at.desc()).all()

    return {
        "workspace_id": workspace.workspace_id,
        "name": workspace.name,
        "description": workspace.description,
        "created_by": workspace.created_by,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
        "pins": pins,
        "changes": changes,
        "change_total": len(changes),
        "priorities": priorities,
        "saved_searches": [
            {
                "saved_search_id": s.saved_search_id,
                "name": s.name,
                "filters": dict(s.filters or {}),
                "created_by": s.created_by,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in saved_searches
        ],
        "bookmarks": [
            {
                "bookmark_id": b.bookmark_id,
                "subject_kind": b.subject_kind,
                "subject_id": b.subject_id,
                "subject_name": b.subject_name,
                "name": b.name,
                "created_by": b.created_by,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in bookmarks
        ],
        "notes": _workspace_notes(db, workspace_id),
    }
