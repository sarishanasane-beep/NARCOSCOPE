from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utcnow

# Explicit review decisions for a record pair. A KEEP_SEPARATE decision
# prevents the pair from being re-flagged as a duplicate on every scan.
DECISION_KEEP_SEPARATE = "KEEP_SEPARATE"


class DuplicateDecision(Base):
    """An explicit human decision about a possible-duplicate pair.

    Only conservative, reviewable outcomes are stored — the system never
    silently merges ambiguous records. The decision keys are canonicalized
    (kind + sorted pair of record ids) so repeat flags are suppressed.
    """

    __tablename__ = "duplicate_decisions"

    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # entity | case
    record_a_id: Mapped[str] = mapped_column(String(36), nullable=False)
    record_b_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
