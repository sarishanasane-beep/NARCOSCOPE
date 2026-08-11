"""Investigator annotations (Prompt 2 Part 3).

Bookmarks, investigator notes and saved searches.

Notes are investigator-created annotations ONLY — they NEVER become
evidence, facts, relationships, claims or graph edges automatically
(OFFICIAL FACT vs INVESTIGATOR NOTE are kept distinct by construction:
notes are never read by extraction, persistence or graph code).

Saved searches store the structured ``InvestigationQuery`` filter set and
re-run through the one global query engine.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.bookmark import Bookmark
from app.models.case import Case
from app.models.entity import Entity
from app.models.event import Event
from app.models.investigator_note import InvestigatorNote
from app.models.location import Location
from app.models.relationship import Relationship
from app.models.saved_search import SavedSearch
from app.services.search.query import InvestigationQuery, run_query
from app.utils.errors import NotFoundError, ValidationError

BOOKMARK_KINDS = ("entity", "case", "event", "location", "relationship", "change")
_BOOKMARK_MODELS = {
    "entity": Entity,
    "case": Case,
    "event": Event,
    "location": Location,
    "relationship": Relationship,
}

NOTE_SUBJECT_KINDS = ("entity", "case", "event", "location", "workspace", "change", "relationship")


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------


def create_bookmark(
    db: Session,
    subject_kind: str,
    subject_id: str,
    subject_name: str | None = None,
    name: str | None = None,
    created_by: str | None = None,
) -> Bookmark:
    kind = {"person": "entity", "organization": "entity"}.get(subject_kind, subject_kind)
    if kind not in BOOKMARK_KINDS:
        raise ValidationError(f"Unsupported bookmark subject kind '{subject_kind}'.")
    model = _BOOKMARK_MODELS.get(kind)
    if model is not None and db.get(model, subject_id) is None:
        raise ValidationError(f"{kind.capitalize()} not found.")
    existing = (
        db.query(Bookmark)
        .filter(Bookmark.subject_kind == kind, Bookmark.subject_id == subject_id)
        .first()
    )
    if existing is not None:
        return existing
    bookmark = Bookmark(
        bookmark_id=str(uuid.uuid4()),
        subject_kind=kind,
        subject_id=subject_id,
        subject_name=subject_name,
        name=name,
        created_by=created_by,
    )
    db.add(bookmark)
    db.commit()
    return bookmark


def list_bookmarks(db: Session, subject_kind: str | None = None) -> list[Bookmark]:
    query = db.query(Bookmark).order_by(Bookmark.created_at.desc())
    if subject_kind:
        query = query.filter(Bookmark.subject_kind == subject_kind)
    return query.all()


def delete_bookmark(db: Session, bookmark_id: str) -> None:
    bookmark = db.get(Bookmark, bookmark_id)
    if bookmark is None:
        raise NotFoundError("Bookmark not found.")
    db.delete(bookmark)
    db.commit()


def bookmark_out(bookmark: Bookmark) -> dict[str, Any]:
    return {
        "bookmark_id": bookmark.bookmark_id,
        "subject_kind": bookmark.subject_kind,
        "subject_id": bookmark.subject_id,
        "subject_name": bookmark.subject_name,
        "name": bookmark.name,
        "created_by": bookmark.created_by,
        "created_at": bookmark.created_at.isoformat() if bookmark.created_at else None,
    }


# ---------------------------------------------------------------------------
# Investigator notes
# ---------------------------------------------------------------------------


def create_note(
    db: Session,
    content: str,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    created_by: str | None = None,
) -> InvestigatorNote:
    if not content or not content.strip():
        raise ValidationError("Note content is required.")
    if subject_kind is not None and subject_kind not in NOTE_SUBJECT_KINDS:
        raise ValidationError(f"Unsupported note subject kind '{subject_kind}'.")
    note = InvestigatorNote(
        note_id=str(uuid.uuid4()),
        subject_kind=subject_kind,
        subject_id=subject_id,
        content=content.strip(),
        created_by=created_by,
    )
    db.add(note)
    db.commit()
    return note


def list_notes(
    db: Session, subject_kind: str | None = None, subject_id: str | None = None
) -> list[InvestigatorNote]:
    query = db.query(InvestigatorNote).order_by(InvestigatorNote.created_at.desc())
    if subject_kind:
        query = query.filter(InvestigatorNote.subject_kind == subject_kind)
    if subject_id:
        query = query.filter(InvestigatorNote.subject_id == subject_id)
    return query.all()


def update_note(db: Session, note_id: str, content: str) -> InvestigatorNote:
    note = db.get(InvestigatorNote, note_id)
    if note is None:
        raise NotFoundError("Note not found.")
    if not content or not content.strip():
        raise ValidationError("Note content cannot be empty.")
    note.content = content.strip()
    db.commit()
    return note


def delete_note(db: Session, note_id: str) -> None:
    note = db.get(InvestigatorNote, note_id)
    if note is None:
        raise NotFoundError("Note not found.")
    db.delete(note)
    db.commit()


def note_out(note: InvestigatorNote) -> dict[str, Any]:
    return {
        "note_id": note.note_id,
        "subject_kind": note.subject_kind,
        "subject_id": note.subject_id,
        "content": note.content,
        "created_by": note.created_by,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Saved searches
# ---------------------------------------------------------------------------

_SEARCH_FIELDS = set(InvestigationQuery.__dataclass_fields__)


def create_saved_search(
    db: Session, name: str, filters: dict, created_by: str | None = None
) -> SavedSearch:
    if not name or not name.strip():
        raise ValidationError("Saved search name is required.")
    unknown = set(filters) - _SEARCH_FIELDS
    if unknown:
        raise ValidationError(f"Unknown filter field(s): {sorted(unknown)}")
    saved = SavedSearch(
        saved_search_id=str(uuid.uuid4()),
        name=name.strip(),
        filters=dict(filters),
        created_by=created_by,
    )
    db.add(saved)
    db.commit()
    return saved


def list_saved_searches(db: Session) -> list[SavedSearch]:
    return db.query(SavedSearch).order_by(SavedSearch.created_at.desc()).all()


def get_saved_search(db: Session, saved_search_id: str) -> SavedSearch:
    saved = db.get(SavedSearch, saved_search_id)
    if saved is None:
        raise NotFoundError("Saved search not found.")
    return saved


def run_saved_search(db: Session, saved_search_id: str) -> dict[str, Any]:
    saved = get_saved_search(db, saved_search_id)
    query = InvestigationQuery.from_dict(saved.filters or {})
    return run_query(db, query)


def delete_saved_search(db: Session, saved_search_id: str) -> None:
    saved = get_saved_search(db, saved_search_id)
    db.delete(saved)
    db.commit()


def saved_search_out(saved: SavedSearch) -> dict[str, Any]:
    return {
        "saved_search_id": saved.saved_search_id,
        "name": saved.name,
        "filters": dict(saved.filters or {}),
        "created_by": saved.created_by,
        "created_at": saved.created_at.isoformat() if saved.created_at else None,
    }
