from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None
    created_by: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class PinAdd(BaseModel):
    kind: str
    id: str
    name: str | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_id: str
    name: str
    description: str | None = None
    pins: list[dict[str, Any]] = []
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceList(BaseModel):
    items: list[WorkspaceOut]
    total: int


# ---------------------------------------------------------------------------
# Prompt 2 Part 4 — final investigation workspace overview
# ---------------------------------------------------------------------------


class ResolvedPin(BaseModel):
    kind: str
    id: str
    name: str | None = None
    type: str = "OTHER"
    exists: bool = True
    # Underlying trusted Entity identity. Only present for pin kinds
    # whose trusted record actually has an entity (locations expose
    # entity_id distinct from their location_id primary key); None for
    # case/event/relationship pins which have no entity record.
    entity_id: str | None = None


class WorkspacePriority(BaseModel):
    entity_id: str
    total: float
    breakdown: dict[str, Any] = {}
    disclaimer: str


class WorkspaceChange(BaseModel):
    change_id: str
    snapshot_id: str
    category: str
    significance: str
    kind: str
    reference_id: str | None = None
    details: dict[str, Any] = {}
    created_at: datetime | None = None


class WorkspaceSavedSearch(BaseModel):
    saved_search_id: str
    name: str
    filters: dict[str, Any] = {}
    created_by: str | None = None
    created_at: datetime | None = None


class WorkspaceBookmark(BaseModel):
    bookmark_id: str
    subject_kind: str
    subject_id: str
    subject_name: str | None = None
    name: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None


class WorkspaceNote(BaseModel):
    note_id: str
    subject_kind: str | None = None
    subject_id: str | None = None
    content: str
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkspaceOverview(BaseModel):
    workspace_id: str
    name: str
    description: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    pins: list[ResolvedPin] = []
    changes: list[WorkspaceChange] = []
    change_total: int = 0
    priorities: list[WorkspacePriority] = []
    saved_searches: list[WorkspaceSavedSearch] = []
    bookmarks: list[WorkspaceBookmark] = []
    notes: list[WorkspaceNote] = []
