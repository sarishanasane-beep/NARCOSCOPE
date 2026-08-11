"""Investigator bookmark API (Prompt 2 Part 3)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.annotations import BookmarkCreate, BookmarkList, BookmarkOut
from app.services.workspaces.annotations import create_bookmark, delete_bookmark, list_bookmarks

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get("", response_model=BookmarkList)
def bookmarks_list(
    subject_kind: str | None = None, db: Session = Depends(get_db)
) -> BookmarkList:
    items = list_bookmarks(db, subject_kind=subject_kind)
    return BookmarkList(items=[BookmarkOut.model_validate(b) for b in items], total=len(items))


@router.post("", response_model=BookmarkOut, status_code=201)
def bookmarks_create(payload: BookmarkCreate, db: Session = Depends(get_db)) -> BookmarkOut:
    bookmark = create_bookmark(
        db,
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        subject_name=payload.subject_name,
        name=payload.name,
        created_by=payload.created_by,
    )
    return BookmarkOut.model_validate(bookmark)


@router.delete("/{bookmark_id}", status_code=204)
def bookmarks_delete(bookmark_id: str, db: Session = Depends(get_db)) -> None:
    delete_bookmark(db, bookmark_id)
