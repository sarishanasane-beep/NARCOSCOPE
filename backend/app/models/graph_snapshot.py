"""Trusted graph snapshot.

A snapshot stores a deterministic, serializable representation of the
TRUSTED graph (nodes + edges) plus a SHA-256 hash. It is created on
demand (e.g. after a confirmed update) and is never overwritten —
snapshots are immutable. Candidate information is never included.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utcnow


class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Deterministic canonical serialization {nodes: [...], edges: [...]}.
    snapshot_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Optional metadata (e.g. created_by, label context).
    metadata_: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
