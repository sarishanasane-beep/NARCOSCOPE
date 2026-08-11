"""Saved investigation search API (Prompt 2 Part 3).

Saved searches store the structured InvestigationQuery filter set and
re-run through the ONE global query engine.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.annotations import SavedSearchCreate, SavedSearchList, SavedSearchOut
from app.services.workspaces.annotations import (
    create_saved_search,
    delete_saved_search,
    get_saved_search,
    list_saved_searches,
    run_saved_search,
)

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])


@router.get("", response_model=SavedSearchList)
def saved_searches_list(db: Session = Depends(get_db)) -> SavedSearchList:
    items = list_saved_searches(db)
    return SavedSearchList(
        items=[SavedSearchOut.model_validate(s) for s in items], total=len(items)
    )


@router.post("", response_model=SavedSearchOut, status_code=201)
def saved_searches_create(
    payload: SavedSearchCreate, db: Session = Depends(get_db)
) -> SavedSearchOut:
    saved = create_saved_search(
        db, name=payload.name, filters=payload.filters, created_by=payload.created_by
    )
    return SavedSearchOut.model_validate(saved)


@router.get("/{saved_search_id}", response_model=SavedSearchOut)
def saved_searches_get(
    saved_search_id: str, db: Session = Depends(get_db)
) -> SavedSearchOut:
    return SavedSearchOut.model_validate(get_saved_search(db, saved_search_id))


@router.get("/{saved_search_id}/run")
def saved_searches_run(saved_search_id: str, db: Session = Depends(get_db)) -> dict:
    """Re-run a saved investigation query against current data."""
    return run_saved_search(db, saved_search_id)


@router.delete("/{saved_search_id}", status_code=204)
def saved_searches_delete(saved_search_id: str, db: Session = Depends(get_db)) -> None:
    delete_saved_search(db, saved_search_id)
