"""Detected trusted-graph change (snapshot comparison result).

One row per detected change between two snapshots. Categories and
significance are assigned by deterministic rules (see
app/services/graph/changes.py). NEW_SUPPORTING_EVIDENCE is emitted when
an existing relationship (same endpoints + type) gains a new evidence
reference — never misreported as a NEW_RELATIONSHIP.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utcnow


class GraphChange(Base):
    __tablename__ = "graph_changes"

    change_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("graph_snapshots.snapshot_id"), nullable=False, index=True
    )
    # NEW_ENTITY | NEW_RELATIONSHIP | REMOVED_ENTITY | REMOVED_RELATIONSHIP |
    # CHANGED_RELATIONSHIP | NEW_CROSS_CASE_CONNECTION | CASE_OVERLAP |
    # NETWORK_GROWTH | NEW_SUPPORTING_EVIDENCE
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    # MAJOR | MODERATE | MINOR
    significance: Mapped[str] = mapped_column(String(20), nullable=False)
    # added | removed | updated | aggregate
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Graph node/edge id the change refers to (or None for aggregates).
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
