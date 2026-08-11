from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.audit import AuditLogList, AuditLogOut
from app.services.audit.service import list_audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditLogList)
def get_audit(
    action: str | None = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)
) -> AuditLogList:
    items = list_audit(db, limit=limit, offset=offset, action=action)
    return AuditLogList(items=[AuditLogOut.model_validate(a) for a in items], total=len(items))
