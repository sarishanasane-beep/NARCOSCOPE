"""Trusted graph snapshots (Prompt 2 Part 3).

A snapshot stores a deterministic, serializable representation of the
TRUSTED graph (nodes + edges) plus a SHA-256 hash. Snapshots are
immutable — they are never overwritten. Candidate information is never
included: the data comes exclusively from ``build_trusted_graph``.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.graph_snapshot import GraphSnapshot
from app.services.graph.builder import build_trusted_graph
from app.utils.errors import NotFoundError


def canonical_graph_data(db: Session) -> dict:
    """Deterministic serialization of the trusted graph."""
    nodes, edges = build_trusted_graph(db)
    node_list = [n.to_dict() for n in sorted(nodes.values(), key=lambda n: n.id)]
    edge_list = [e.to_dict() for e in sorted(edges, key=lambda e: e.id)]
    return {"nodes": node_list, "edges": edge_list}


def graph_hash(data: dict) -> str:
    """SHA-256 of the canonical JSON representation."""
    payload = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_snapshot(
    db: Session, label: str | None = None, created_by: str | None = None
) -> GraphSnapshot:
    """Create a new immutable snapshot of the current trusted graph."""
    data = canonical_graph_data(db)
    version = (db.query(func.max(GraphSnapshot.version)).scalar() or 0) + 1
    snapshot = GraphSnapshot(
        snapshot_id=str(uuid.uuid4()),
        version=version,
        label=label,
        graph_hash=graph_hash(data),
        node_count=len(data["nodes"]),
        edge_count=len(data["edges"]),
        snapshot_data=data,
        metadata_={"created_by": created_by} if created_by else {},
    )
    db.add(snapshot)
    db.commit()
    return snapshot


def list_snapshots(db: Session) -> list[GraphSnapshot]:
    return db.query(GraphSnapshot).order_by(GraphSnapshot.version.desc()).all()


def get_snapshot(db: Session, snapshot_id: str) -> GraphSnapshot:
    snapshot = db.get(GraphSnapshot, snapshot_id)
    if snapshot is None:
        raise NotFoundError("Snapshot not found.")
    return snapshot
