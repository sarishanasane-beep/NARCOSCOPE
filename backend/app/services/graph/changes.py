"""Snapshot comparison / change detection (Prompt 2 Part 3).

Compares two snapshots of the TRUSTED graph and emits deterministic
changes grouped by category and significance.

Categories:
  NEW_ENTITY | REMOVED_ENTITY | NEW_RELATIONSHIP | REMOVED_RELATIONSHIP |
  CHANGED_RELATIONSHIP | NEW_CROSS_CASE_CONNECTION | CASE_OVERLAP |
  NETWORK_GROWTH | NEW_SUPPORTING_EVIDENCE

Critical rule: when an EXISTING relationship (same source + target +
type) gains a new evidence reference, it is reported as
NEW_SUPPORTING_EVIDENCE — never as a NEW_RELATIONSHIP.

Significance rules (deterministic, documented):
  - NEW/REMOVED entity: MAJOR for PERSON/ORGANIZATION/AGENCY,
    MODERATE for LOCATION/EVENT/CASE, MINOR otherwise.
  - NEW_RELATIONSHIP: MODERATE; MAJOR when it is a cross-case connection.
  - REMOVED_RELATIONSHIP / CHANGED_RELATIONSHIP: MODERATE (MINOR when only
    confidence changed... see code), NEW_SUPPORTING_EVIDENCE: MINOR.
  - CASE_OVERLAP (entity gained a case): MAJOR.
  - NETWORK_GROWTH: MODERATE, MAJOR when growth exceeds 50%.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models.graph_change import GraphChange
from app.models.graph_snapshot import GraphSnapshot
from app.utils.errors import NotFoundError, ValidationError

NEW_ENTITY = "NEW_ENTITY"
REMOVED_ENTITY = "REMOVED_ENTITY"
NEW_RELATIONSHIP = "NEW_RELATIONSHIP"
REMOVED_RELATIONSHIP = "REMOVED_RELATIONSHIP"
CHANGED_RELATIONSHIP = "CHANGED_RELATIONSHIP"
NEW_CROSS_CASE_CONNECTION = "NEW_CROSS_CASE_CONNECTION"
CASE_OVERLAP = "CASE_OVERLAP"
NETWORK_GROWTH = "NETWORK_GROWTH"
NEW_SUPPORTING_EVIDENCE = "NEW_SUPPORTING_EVIDENCE"

MAJOR = "MAJOR"
MODERATE = "MODERATE"
MINOR = "MINOR"

SIGNIFICANCE_ORDER = {MAJOR: 0, MODERATE: 1, MINOR: 2}


def _edge_key(edge: dict) -> tuple[str, str, str]:
    return (edge.get("source"), edge.get("target"), edge.get("relationship_type"))


def _entity_significance(node: dict) -> str:
    node_type = node.get("type")
    if node_type in ("PERSON", "ORGANIZATION", "AGENCY"):
        return MAJOR
    if node_type in ("LOCATION", "EVENT", "CASE"):
        return MODERATE
    return MINOR


def _entity_case_ids(nodes: list[dict], edges: list[dict]) -> dict[str, set[str]]:
    """entity node id -> set of case ids it is documented in."""
    membership: dict[str, set[str]] = {}
    event_to_case: dict[str, str] = {}
    for edge in edges:
        if edge.get("relationship_type") == "PART_OF" and edge.get("event_id"):
            if edge.get("case_id"):
                event_to_case[edge["event_id"]] = edge["case_id"]
        case_id = edge.get("case_id")
        if case_id:
            membership.setdefault(edge["source"], set()).add(case_id)
            membership.setdefault(edge["target"], set()).add(case_id)
    for node in nodes:
        if node.get("node_kind") == "event" and node.get("event_id"):
            case_id = event_to_case.get(node["event_id"])
            if case_id:
                membership.setdefault(node["id"], set()).add(case_id)
    return membership


def compare_graph_data(prev: dict, curr: dict) -> list[dict[str, Any]]:
    """Deterministic change list between two canonical graph payloads."""
    changes: list[dict[str, Any]] = []
    prev_nodes = {n["id"]: n for n in prev["nodes"]}
    curr_nodes = {n["id"]: n for n in curr["nodes"]}
    prev_edges = {_edge_key(e): e for e in prev["edges"]}
    curr_edges = {_edge_key(e): e for e in curr["edges"]}

    # --- Entities ---
    for node_id, node in curr_nodes.items():
        if node_id not in prev_nodes:
            changes.append(
                {
                    "category": NEW_ENTITY,
                    "kind": "added",
                    "reference_id": node_id,
                    "significance": _entity_significance(node),
                    "details": {
                        "id": node_id,
                        "name": node.get("name"),
                        "type": node.get("type"),
                    },
                }
            )
    for node_id, node in prev_nodes.items():
        if node_id not in curr_nodes:
            changes.append(
                {
                    "category": REMOVED_ENTITY,
                    "kind": "removed",
                    "reference_id": node_id,
                    "significance": _entity_significance(node),
                    "details": {
                        "id": node_id,
                        "name": node.get("name"),
                        "type": node.get("type"),
                    },
                }
            )

    prev_membership = _entity_case_ids(prev["nodes"], prev["edges"])
    curr_membership = _entity_case_ids(curr["nodes"], curr["edges"])

    # --- Case overlap (entity gained additional case membership) ---
    for node_id, node in curr_nodes.items():
        prev_cases = prev_membership.get(node_id, set())
        curr_cases = curr_membership.get(node_id, set())
        if len(curr_cases) > len(prev_cases) and len(curr_cases) >= 2:
            changes.append(
                {
                    "category": CASE_OVERLAP,
                    "kind": "aggregate",
                    "reference_id": node_id,
                    "significance": MAJOR,
                    "details": {
                        "name": node.get("name"),
                        "type": node.get("type"),
                        "previous_cases": sorted(prev_cases),
                        "new_cases": sorted(curr_cases - prev_cases),
                    },
                }
            )

    # --- Edges ---
    for key, edge in curr_edges.items():
        prev_edge = prev_edges.get(key)
        if prev_edge is None:
            endpoints_cross = (
                key[0] in curr_membership
                and len(curr_membership[key[0]]) >= 2
                and key[1] in curr_membership
                and len(curr_membership[key[1]]) >= 2
            )
            category = NEW_CROSS_CASE_CONNECTION if endpoints_cross else NEW_RELATIONSHIP
            changes.append(
                {
                    "category": category,
                    "kind": "added",
                    "reference_id": edge.get("id"),
                    "significance": MAJOR if endpoints_cross else MODERATE,
                    "details": {
                        "source": key[0],
                        "target": key[1],
                        "relationship_type": key[2],
                        "id": edge.get("id"),
                        "classification": edge.get("classification"),
                        "evidence_id": edge.get("evidence_id"),
                    },
                }
            )
        else:
            same_evidence = prev_edge.get("evidence_id") == edge.get("evidence_id")
            attrs_changed = any(
                prev_edge.get(attr) != edge.get(attr)
                for attr in ("confidence", "classification", "updated_at")
            )
            if not same_evidence:
                # Existing relationship (same triple) gained/changed evidence —
                # this is NEW SUPPORTING EVIDENCE, never a new relationship.
                changes.append(
                    {
                        "category": NEW_SUPPORTING_EVIDENCE,
                        "kind": "updated",
                        "reference_id": edge.get("id"),
                        "significance": MINOR,
                        "details": {
                            "source": key[0],
                            "target": key[1],
                            "relationship_type": key[2],
                            "previous_evidence_id": prev_edge.get("evidence_id"),
                            "new_evidence_id": edge.get("evidence_id"),
                        },
                    }
                )
            elif attrs_changed:
                changes.append(
                    {
                        "category": CHANGED_RELATIONSHIP,
                        "kind": "updated",
                        "reference_id": edge.get("id"),
                        "significance": (
                            MODERATE
                            if prev_edge.get("classification") != edge.get("classification")
                            else MINOR
                        ),
                        "details": {
                            "source": key[0],
                            "target": key[1],
                            "relationship_type": key[2],
                            "previous": {
                                "confidence": prev_edge.get("confidence"),
                                "classification": prev_edge.get("classification"),
                            },
                            "current": {
                                "confidence": edge.get("confidence"),
                                "classification": edge.get("classification"),
                            },
                        },
                    }
                )
    for key, edge in prev_edges.items():
        if key not in curr_edges:
            changes.append(
                {
                    "category": REMOVED_RELATIONSHIP,
                    "kind": "removed",
                    "reference_id": edge.get("id"),
                    "significance": MODERATE,
                    "details": {
                        "source": key[0],
                        "target": key[1],
                        "relationship_type": key[2],
                        "id": edge.get("id"),
                    },
                }
            )

    # --- Network growth (aggregate) ---
    prev_total = len(prev["nodes"]) + len(prev["edges"])
    curr_total = len(curr["nodes"]) + len(curr["edges"])
    if curr_total > prev_total:
        growth_ratio = (curr_total - prev_total) / max(1, prev_total)
        changes.append(
            {
                "category": NETWORK_GROWTH,
                "kind": "aggregate",
                "reference_id": None,
                "significance": MAJOR if growth_ratio > 0.5 else MODERATE,
                "details": {
                    "previous_nodes": len(prev["nodes"]),
                    "current_nodes": len(curr["nodes"]),
                    "previous_edges": len(prev["edges"]),
                    "current_edges": len(curr["edges"]),
                },
            }
        )

    return changes


def summarize_changes(changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Grouped summary: total, by category, by significance."""
    by_category = Counter(c["category"] for c in changes)
    by_significance = Counter(c["significance"] for c in changes)
    return {
        "total": len(changes),
        "by_category": dict(sorted(by_category.items())),
        "by_significance": dict(sorted(by_significance.items())),
        "major": by_significance.get(MAJOR, 0),
        "moderate": by_significance.get(MODERATE, 0),
        "minor": by_significance.get(MINOR, 0),
    }


def persist_changes(
    db: Session, snapshot_id: str, changes: list[dict[str, Any]]
) -> list[GraphChange]:
    rows: list[GraphChange] = []
    for change in changes:
        row = GraphChange(
            change_id=str(uuid.uuid4()),
            snapshot_id=snapshot_id,
            category=change["category"],
            significance=change["significance"],
            kind=change["kind"],
            reference_id=change.get("reference_id"),
            details=change.get("details") or {},
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def compare_snapshots(db: Session, previous_id: str, current_id: str) -> dict[str, Any]:
    """Compare two snapshots: persist + summarize the detected changes."""
    previous = db.get(GraphSnapshot, previous_id)
    if previous is None:
        raise NotFoundError("Previous snapshot not found.")
    current = db.get(GraphSnapshot, current_id)
    if current is None:
        raise NotFoundError("Current snapshot not found.")
    if previous.snapshot_id == current.snapshot_id:
        raise ValidationError("Compare two different snapshots.")
    # Re-comparison is idempotent: replace prior change rows for the snapshot.
    db.query(GraphChange).filter(GraphChange.snapshot_id == current.snapshot_id).delete()
    db.flush()
    changes = compare_graph_data(previous.snapshot_data, current.snapshot_data)
    rows = persist_changes(db, current.snapshot_id, changes)
    summary = summarize_changes(changes)
    return {
        "previous_snapshot_id": previous.snapshot_id,
        "current_snapshot_id": current.snapshot_id,
        **summary,
        "changes": [_change_out(row) for row in rows],
    }


def _change_out(row: GraphChange) -> dict[str, Any]:
    return {
        "change_id": row.change_id,
        "snapshot_id": row.snapshot_id,
        "category": row.category,
        "significance": row.significance,
        "kind": row.kind,
        "reference_id": row.reference_id,
        "details": row.details or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
