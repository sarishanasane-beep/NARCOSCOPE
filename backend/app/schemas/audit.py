from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class AuditLogOut(ORMModel):
    log_id: str
    action: str
    object_type: str
    object_id: str
    previous_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    reason: str | None = None
    user: str | None = None
    timestamp: datetime


class AuditLogList(BaseModel):
    items: list[AuditLogOut]
    total: int = 0
