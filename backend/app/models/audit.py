from datetime import datetime

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utcnow

ACTION_CREATE = "CREATE"
ACTION_UPDATE = "UPDATE"
ACTION_CONFIRM = "CONFIRM"
ACTION_REJECT = "REJECT"
ACTION_MERGE = "MERGE"
ACTION_UNMERGE = "UNMERGE"
ACTION_DELETE = "DELETE"


class AuditLog(Base):
    """Append-only audit trail.

    Tracks action, object type/id, previous/new values, timestamp, user
    (when authentication exists) and reason. Important evidence is never
    permanently deleted without a clear mechanism.
    """

    __tablename__ = "audit_logs"

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_id: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
