"""Investigation workspace API (Prompt 2 Part 3)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.workspaces import (
    PinAdd,
    WorkspaceCreate,
    WorkspaceList,
    WorkspaceOut,
    WorkspaceOverview,
    WorkspaceUpdate,
)
from app.services.workspaces.service import (
    add_pin,
    create_workspace,
    delete_workspace,
    get_workspace,
    list_workspaces,
    remove_pin,
    update_workspace,
    workspace_overview,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=WorkspaceList)
def workspaces_list(db: Session = Depends(get_db)) -> WorkspaceList:
    items = list_workspaces(db)
    return WorkspaceList(items=[WorkspaceOut.model_validate(w) for w in items], total=len(items))


@router.post("", response_model=WorkspaceOut, status_code=201)
def workspaces_create(payload: WorkspaceCreate, db: Session = Depends(get_db)) -> WorkspaceOut:
    workspace = create_workspace(
        db, name=payload.name, description=payload.description, created_by=payload.created_by
    )
    return WorkspaceOut.model_validate(workspace)


@router.get("/{workspace_id}/overview", response_model=WorkspaceOverview)
def workspaces_overview(
    workspace_id: str, db: Session = Depends(get_db)
) -> WorkspaceOverview:
    """Final investigation workspace: pinned subjects (resolved against
    current trusted data), relevant changes, priority for pinned
    entities, saved searches, bookmarks and workspace notes."""
    return WorkspaceOverview(**workspace_overview(db, workspace_id))


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def workspaces_get(workspace_id: str, db: Session = Depends(get_db)) -> WorkspaceOut:
    return WorkspaceOut.model_validate(get_workspace(db, workspace_id))


@router.put("/{workspace_id}", response_model=WorkspaceOut)
def workspaces_update(
    workspace_id: str, payload: WorkspaceUpdate, db: Session = Depends(get_db)
) -> WorkspaceOut:
    workspace = update_workspace(
        db, workspace_id, name=payload.name, description=payload.description
    )
    return WorkspaceOut.model_validate(workspace)


@router.delete("/{workspace_id}", status_code=204)
def workspaces_delete(workspace_id: str, db: Session = Depends(get_db)) -> None:
    delete_workspace(db, workspace_id)


@router.post("/{workspace_id}/pins", response_model=WorkspaceOut)
def workspaces_add_pin(
    workspace_id: str, payload: PinAdd, db: Session = Depends(get_db)
) -> WorkspaceOut:
    workspace = add_pin(
        db, workspace_id, kind=payload.kind, subject_id=payload.id, name=payload.name
    )
    return WorkspaceOut.model_validate(workspace)


@router.delete("/{workspace_id}/pins/{index}", response_model=WorkspaceOut)
def workspaces_remove_pin(
    workspace_id: str, index: int, db: Session = Depends(get_db)
) -> WorkspaceOut:
    workspace = remove_pin(db, workspace_id, index)
    return WorkspaceOut.model_validate(workspace)
