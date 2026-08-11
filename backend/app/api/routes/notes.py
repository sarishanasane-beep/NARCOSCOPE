"""Investigator note API (Prompt 2 Part 3).

Notes are investigator-created annotations ONLY — they never become
evidence, facts, relationships, claims or graph edges automatically.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.annotations import NoteCreate, NoteList, NoteOut, NoteUpdate
from app.services.workspaces.annotations import (
    create_note,
    delete_note,
    list_notes,
    update_note,
)

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=NoteList)
def notes_list(
    subject_kind: str | None = None,
    subject_id: str | None = None,
    db: Session = Depends(get_db),
) -> NoteList:
    items = list_notes(db, subject_kind=subject_kind, subject_id=subject_id)
    return NoteList(items=[NoteOut.model_validate(n) for n in items], total=len(items))


@router.post("", response_model=NoteOut, status_code=201)
def notes_create(payload: NoteCreate, db: Session = Depends(get_db)) -> NoteOut:
    note = create_note(
        db,
        content=payload.content,
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        created_by=payload.created_by,
    )
    return NoteOut.model_validate(note)


@router.put("/{note_id}", response_model=NoteOut)
def notes_update(note_id: str, payload: NoteUpdate, db: Session = Depends(get_db)) -> NoteOut:
    note = update_note(db, note_id, content=payload.content)
    return NoteOut.model_validate(note)


@router.delete("/{note_id}", status_code=204)
def notes_delete(note_id: str, db: Session = Depends(get_db)) -> None:
    delete_note(db, note_id)
