"""Investigation Priority (Prompt 2 Part 3).

A deterministic analytical score (0-100) that helps an investigator
decide what information may deserve review first. It is NOT guilt,
criminality, suspect probability, or a likelihood of committing a crime.

Breakdown (documented, deterministic):
  Recency           0-30  30 * exp(-days_since_last_change / 90)
  Cross-cluster     0-25  25 * (distinct neighbor clusters / total neighbors)
  Centrality        0-20  20 * normalized degree centrality (degree/(n-1))
  Case relevance    0-15  15 when directly documented in the selected case;
                           otherwise 5 per confirmed case link (cap 15);
                           without a selected case: 5 per distinct case (cap 15)
  Source diversity  0-10  2.5 per distinct publisher/source-type dimension (cap 10)

The decay constant is 90 days. All inputs come from the TRUSTED graph and
confirmed records only — candidate data never influences the score.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.entity import ENTITY_STATUS_ACTIVE, Entity
from app.models.evidence import Evidence
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
from app.services.graph.analytics import _simple_graph, cluster_membership
from app.services.graph.model import entity_node_id
from app.utils.errors import NotFoundError

DECAY_CONSTANT_DAYS = 90.0

DISCLAIMER = (
    "Investigation Priority is an analytical signal to help decide what "
    "information may deserve review first. It is NOT guilt, criminality, "
    "suspect probability, or a likelihood of committing a crime."
)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _confirmed_links(db: Session, entity_id: str) -> tuple[list[Relationship], list[Fact]]:
    rels = (
        db.query(Relationship)
        .filter(
            Relationship.status == REL_STATUS_CONFIRMED,
            or_(
                Relationship.source_entity_id == entity_id,
                Relationship.target_entity_id == entity_id,
            ),
        )
        .all()
    )
    facts = (
        db.query(Fact)
        .filter(
            Fact.status == FACT_STATUS_CONFIRMED,
            or_(
                Fact.subject_entity_id == entity_id,
                Fact.object_entity_id == entity_id,
            ),
        )
        .all()
    )
    return rels, facts


def _recency_score(db: Session, entity_id: str) -> dict[str, Any]:
    updated: list[datetime] = []
    entity = db.get(Entity, entity_id)
    if entity is not None and entity.updated_at is not None:
        updated.append(entity.updated_at)
    rels, facts = _confirmed_links(db, entity_id)
    updated.extend(r.updated_at for r in rels if r.updated_at)
    updated.extend(f.updated_at for f in facts if f.updated_at)
    last = max((_ensure_aware(u) for u in updated), default=datetime.now(timezone.utc))
    days = max(0.0, (datetime.now(timezone.utc) - last).total_seconds() / 86400.0)
    score = round(30.0 * math.exp(-days / DECAY_CONSTANT_DAYS), 2)
    return {
        "score": score,
        "days_since_change": round(days, 1),
        "decay_constant_days": DECAY_CONSTANT_DAYS,
        "explanation": (
            f"30 × exp(-{round(days, 1)} days / {DECAY_CONSTANT_DAYS}) = {score}"
        ),
    }


def _centrality_score(db: Session, entity_id: str) -> dict[str, Any]:
    graph = _simple_graph(db)
    node_id = entity_node_id(entity_id)
    n = graph.number_of_nodes()
    if n <= 1 or node_id not in graph:
        return {
            "score": 0.0,
            "normalized_degree": 0.0,
            "explanation": "Not present in the trusted graph (0 nodes or isolated).",
        }
    normalized = graph.degree(node_id) / (n - 1)
    score = round(20.0 * normalized, 2)
    return {
        "score": score,
        "normalized_degree": round(normalized, 4),
        "degree": int(graph.degree(node_id)),
        "explanation": f"20 × normalized degree ({normalized:.3f}) = {score}",
    }


def _cross_cluster_score(db: Session, entity_id: str) -> dict[str, Any]:
    graph = _simple_graph(db)
    node_id = entity_node_id(entity_id)
    if node_id not in graph:
        return {
            "score": 0.0,
            "distinct_neighbor_clusters": 0,
            "neighbor_count": 0,
            "explanation": "Entity not in the trusted graph.",
        }
    membership = cluster_membership(db)
    my_cluster = membership.get(node_id)
    neighbors = list(graph.neighbors(node_id))
    if my_cluster is None or not neighbors:
        return {
            "score": 0.0,
            "distinct_neighbor_clusters": 0,
            "neighbor_count": len(neighbors),
            "explanation": "No cluster or no neighbors — no cross-cluster signal.",
        }
    distinct = {
        membership.get(nbr) for nbr in neighbors if membership.get(nbr) is not None
    }
    distinct.discard(my_cluster)
    fraction = len(distinct) / len(neighbors)
    score = round(25.0 * fraction, 2)
    return {
        "score": score,
        "distinct_neighbor_clusters": len(distinct),
        "neighbor_count": len(neighbors),
        "explanation": f"25 × ({len(distinct)} distinct neighbor clusters / {len(neighbors)} neighbors) = {score}",
    }


def _case_relevance_score(
    db: Session, entity_id: str, case_id: str | None = None
) -> dict[str, Any]:
    rels, facts = _confirmed_links(db, entity_id)
    case_ids = {
        r.case_id for r in rels if r.case_id
    } | {f.case_id for f in facts if f.case_id}
    if case_id:
        if case_id in case_ids:
            score = 15.0
            explanation = "Directly documented in the selected case (15/15)."
        else:
            linked = sum(
                1
                for r in rels
                if r.case_id == case_id
            ) + sum(1 for f in facts if f.case_id == case_id)
            score = min(15.0, 5.0 * linked)
            explanation = (
                f"Not directly in the selected case; {linked} confirmed link(s) × 5 "
                f"(cap 15) = {score}."
            )
    else:
        score = min(15.0, 5.0 * len(case_ids))
        explanation = f"5 × {len(case_ids)} distinct case(s) (cap 15) = {score}."
    return {
        "score": round(score, 2),
        "case_count": len(case_ids),
        "selected_case_id": case_id,
        "explanation": explanation,
    }


def _source_diversity_score(db: Session, entity_id: str) -> dict[str, Any]:
    rels, facts = _confirmed_links(db, entity_id)
    evidence_ids = {
        r.evidence_id for r in rels if r.evidence_id
    } | {f.evidence_id for f in facts if f.evidence_id}
    publishers: set[str] = set()
    source_types: set[str] = set()
    for evidence_id in evidence_ids:
        evidence = db.get(Evidence, evidence_id)
        if evidence is None:
            continue
        source = evidence.source
        if source is None:
            source_types.add("DIRECT_DOCUMENT")
            continue
        if source.publisher:
            publishers.add(source.publisher)
        if source.source_type:
            source_types.add(source.source_type)
    dimensions = publishers | source_types
    score = min(10.0, 2.5 * len(dimensions))
    return {
        "score": round(score, 2),
        "distinct_publishers": sorted(publishers),
        "distinct_source_types": sorted(source_types),
        "explanation": (
            f"2.5 × {len(dimensions)} distinct source dimension(s) "
            f"(publishers + source types, cap 10) = {round(score, 2)}."
        ),
    }


def priority_for_entity(
    db: Session, entity_id: str, case_id: str | None = None
) -> dict[str, Any]:
    """Full 0-100 priority with an explicit breakdown for an entity."""
    if db.get(Entity, entity_id) is None:
        raise NotFoundError("Entity not found.")
    components = {
        "recency": _recency_score(db, entity_id),
        "cross_cluster": _cross_cluster_score(db, entity_id),
        "centrality": _centrality_score(db, entity_id),
        "case_relevance": _case_relevance_score(db, entity_id, case_id=case_id),
        "source_diversity": _source_diversity_score(db, entity_id),
    }
    total = round(sum(c["score"] for c in components.values()), 2)
    return {
        "entity_id": entity_id,
        "total": min(100.0, total),
        "breakdown": components,
        "disclaimer": DISCLAIMER,
    }


def priority_ranking(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    """Top-N ACTIVE entities by Investigation Priority, with breakdowns."""
    entities = (
        db.query(Entity)
        .filter(Entity.status == ENTITY_STATUS_ACTIVE)
        .order_by(Entity.canonical_name)
        .all()
    )
    scored: list[dict[str, Any]] = []
    for entity in entities:
        priority = priority_for_entity(db, entity.entity_id)
        scored.append(
            {
                "entity_id": entity.entity_id,
                "name": entity.canonical_name,
                "entity_type": entity.entity_type,
                **priority,
            }
        )
    scored.sort(key=lambda s: (s["total"], s["entity_id"]), reverse=True)
    return scored[: max(1, min(limit, 200))]
