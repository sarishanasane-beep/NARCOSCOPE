"""Audit log service.

Every meaningful action (create, update, confirm, reject, merge, ...) is
recorded with previous/new values and a reason. Evidence is never
permanently deleted without a clear mechanism.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.utils.logging import log_event
from app.utils.time import utcnow

import logging

logger = logging.getLogger(__name__)


def log_action(
    db: Session,
    *,
    action: str,
    object_type: str,
    object_id: str,
    previous_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
    user: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        log_id=str(uuid.uuid4()),
        action=action,
        object_type=object_type,
        object_id=object_id,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
        user=user,
        timestamp=utcnow(),
    )
    db.add(entry)
    db.flush()
    log_event(logger, f"audit_{action.lower()}", object_type=object_type, object_id=object_id, user=user)
    return entry


def list_audit(db: Session, limit: int = 100, offset: int = 0, action: str | None = None) -> list[AuditLog]:
    query = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if action:
        query = query.filter(AuditLog.action == action)
    return query.offset(offset).limit(limit).all()
