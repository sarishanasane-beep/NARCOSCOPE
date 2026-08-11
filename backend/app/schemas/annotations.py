from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Investigation query (one global query engine)
# ---------------------------------------------------------------------------


class InvestigationQueryIn(BaseModel):
    q: str | None = None
    entity_type: str | None = None
    event_type: str | None = None
    location: str | None = None
    case_number: str | None = None
    relationship_type: str | None = None
    source_type: str | None = None
    claim_status: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 20


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------


class BookmarkCreate(BaseModel):
    subject_kind: str
    subject_id: str
    subject_name: str | None = None
    name: str | None = None
    created_by: str | None = None


class BookmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bookmark_id: str
    subject_kind: str
    subject_id: str
    subject_name: str | None = None
    name: str | None = None
    created_by: str | None = None
    created_at: datetime


class BookmarkList(BaseModel):
    items: list[BookmarkOut]
    total: int


# ---------------------------------------------------------------------------
# Investigator notes
# ---------------------------------------------------------------------------


class NoteCreate(BaseModel):
    content: str
    subject_kind: str | None = None
    subject_id: str | None = None
    created_by: str | None = None


class NoteUpdate(BaseModel):
    content: str


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    note_id: str
    subject_kind: str | None = None
    subject_id: str | None = None
    content: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class NoteList(BaseModel):
    items: list[NoteOut]
    total: int


# ---------------------------------------------------------------------------
# Saved searches
# ---------------------------------------------------------------------------


class SavedSearchCreate(BaseModel):
    name: str
    filters: dict[str, Any] = {}
    created_by: str | None = None


class SavedSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    saved_search_id: str
    name: str
    filters: dict[str, Any] = {}
    created_by: str | None = None
    created_at: datetime


class SavedSearchList(BaseModel):
    items: list[SavedSearchOut]
    total: int
