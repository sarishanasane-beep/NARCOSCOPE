"""Trusted master knowledge graph construction.

Builds nodes and edges EXCLUSIVELY from trusted (confirmed) database
records:

  - ``entities`` (only populated by the confirmation workflow)
  - ``events`` (first-class trusted events)
  - ``cases``
  - relationships with ``status == CONFIRMED`` (DIRECT/DERIVED only)
  - facts with ``status == CONFIRMED``
  - event -> case and event -> location associations
  - the location hierarchy (``parent_location_id``)

Candidate records (PENDING / REJECTED / EDITED) and POSSIBLE_MATCH are
NEVER read here, so unconfirmed information cannot enter the trusted
graph by construction. The database remains the source of truth; the
graph is always reconstructable from it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.entity import ENTITY_STATUS_ACTIVE, ENTITY_STATUS_MERGED, Entity
from app.models.event import Event
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.location import Location
from app.models.relationship import (
    CLASSIFICATION_CANDIDATE,
    REL_STATUS_CONFIRMED,
    Relationship,
)

from app.services.graph.model import (
    GraphEdge,
    GraphNode,
    case_node_id,
    entity_node_id,
    event_node_id,
)

POSSIBLE_MATCH = "POSSIBLE_MATCH"


def canonical_case_endpoints(db: Session) -> dict[str, str]:
    """CASE-typed entity ids -> canonical case node ids.

    Covers both deduplication sources:
      - entities explicitly reconciled into a Case (status MERGED +
        ``merged_into_case_id``),
      - legacy ACTIVE CASE-typed entities whose normalized name matches an
        existing Case record.

    Relationship endpoints are remapped through this table so the graph
    always shows ONE logical CASE node and never a duplicate — the same
    canonical-identity resolution used by the case-scoped graph, applied
    here to the global trusted graph.
    """
    from app.utils.text import normalize_name

    mapping: dict[str, str] = {}
    for case in db.query(Case).filter(Case.merged_into_id.is_(None)).all():
        keys = {
            normalize_name(v)
            for v in (case.case_name, case.operation_name, case.official_case_number)
            if v
        }
        if not keys:
            continue
        for entity in db.query(Entity).filter(Entity.entity_type == "CASE").all():
            if entity.status == ENTITY_STATUS_ACTIVE and normalize_name(entity.canonical_name) in keys:
                mapping[entity.entity_id] = case_node_id(case.case_id)
            elif entity.status == ENTITY_STATUS_MERGED and entity.merged_into_case_id == case.case_id:
                mapping[entity.entity_id] = case_node_id(case.case_id)
    return mapping


def _aliases(entity: Entity) -> list[str]:
    if entity.person is not None:
        return list(entity.person.aliases or [])
    if entity.organization is not None:
        return list(entity.organization.aliases or [])
    return []


def _entity_node(entity: Entity) -> GraphNode:
    meta = entity.structured_metadata or {}
    return GraphNode(
        id=entity_node_id(entity.entity_id),
        name=entity.canonical_name,
        node_kind="entity",
        type=entity.entity_type,
        status=entity.status,
        aliases=_aliases(entity),
        entity_id=entity.entity_id,
        investigative_status=meta.get("investigative_status"),
        mention_context=meta.get("mention_context"),
        role=meta.get("role"),
        document_id=entity.document_id,
    )


def _event_node(event: Event) -> GraphNode:
    return GraphNode(
        id=event_node_id(event.event_id),
        name=event.title,
        node_kind="event",
        type="EVENT",
        status="CONFIRMED",
        event_id=event.event_id,
        event_type=event.event_type,
        date_precision=event.date_precision,
        start_date=event.start_date.isoformat() if event.start_date else None,
        end_date=event.end_date.isoformat() if event.end_date else None,
        document_id=event.document_id,
    )


def _case_node(case: Case) -> GraphNode:
    name = case.case_name or case.official_case_number or f"Case {case.case_id[:8]}"
    return GraphNode(
        id=case_node_id(case.case_id),
        name=name,
        node_kind="case",
        type="CASE",
        status=case.status or "UNKNOWN",
        case_id=case.case_id,
        case_number=case.official_case_number,
        jurisdiction=case.jurisdiction,
        start_date=case.start_date.isoformat() if case.start_date else None,
        end_date=case.end_date.isoformat() if case.end_date else None,
    )


def build_trusted_graph(db: Session) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
    """Return ``(nodes_by_id, edges)`` for the entire trusted graph."""
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    # --- Trusted entities (only created by the confirmation workflow) ---
    # Merged/superseded duplicates (merged_into_id set) are excluded so a
    # canonicalized record never appears alongside its duplicate.
    for entity in (
        db.query(Entity)
        .filter(Entity.status == ENTITY_STATUS_ACTIVE, Entity.merged_into_id.is_(None))
        .all()
    ):
        nodes[entity_node_id(entity.entity_id)] = _entity_node(entity)

    locations = {loc.location_id: loc for loc in db.query(Location).all()}

    # --- Events + event associations ---
    for event in db.query(Event).all():
        event_id = event_node_id(event.event_id)
        nodes[event_id] = _event_node(event)
        if event.case_id:
            edges.append(
                GraphEdge(
                    id=f"ev-case:{event.event_id}:{event.case_id}",
                    source=event_id,
                    target=case_node_id(event.case_id),
                    relationship_type="PART_OF",
                    classification="DIRECT",
                    provenance_kind="event_case",
                    event_id=event.event_id,
                    case_id=event.case_id,
                    created_at=event.created_at.isoformat() if event.created_at else None,
                    updated_at=event.updated_at.isoformat() if event.updated_at else None,
                )
            )
        if event.location_id:
            location = locations.get(event.location_id)
            if location is not None:
                edges.append(
                    GraphEdge(
                        id=f"ev-loc:{event.event_id}:{event.location_id}",
                        source=event_id,
                        target=entity_node_id(location.entity_id),
                        relationship_type="OCCURRED_IN",
                        classification="DIRECT",
                        provenance_kind="event_location",
                        event_id=event.event_id,
                        created_at=event.created_at.isoformat() if event.created_at else None,
                        updated_at=event.updated_at.isoformat() if event.updated_at else None,
                    )
                )

    # --- Cases ---
    for case in db.query(Case).all():
        nodes[case_node_id(case.case_id)] = _case_node(case)

    # --- Confirmed relationships (DIRECT/DERIVED only; never POSSIBLE_MATCH) ---
    # A relationship whose endpoint is a reconciled / legacy CASE-typed
    # entity routes to the canonical CASE node (never a duplicate).
    case_endpoints = canonical_case_endpoints(db)
    for rel in db.query(Relationship).filter(Relationship.status == REL_STATUS_CONFIRMED).all():
        if rel.relationship_type == POSSIBLE_MATCH:
            continue
        if rel.classification == CLASSIFICATION_CANDIDATE:
            continue
        source = case_endpoints.get(rel.source_entity_id, entity_node_id(rel.source_entity_id))
        target = case_endpoints.get(rel.target_entity_id, entity_node_id(rel.target_entity_id))
        if source not in nodes or target not in nodes:
            continue
        edges.append(
            GraphEdge(
                id=f"rel:{rel.relationship_id}",
                source=source,
                target=target,
                relationship_type=rel.relationship_type,
                classification=rel.classification,
                confidence=rel.confidence,
                provenance_kind="relationship",
                relationship_id=rel.relationship_id,
                event_id=rel.event_id,
                case_id=rel.case_id,
                evidence_id=rel.evidence_id,
                created_at=rel.created_at.isoformat() if rel.created_at else None,
                updated_at=rel.updated_at.isoformat() if rel.updated_at else None,
            )
        )

    # --- Confirmed facts (subject -> object entity / case / event) ---
    for fact in db.query(Fact).filter(Fact.status == FACT_STATUS_CONFIRMED).all():
        source = entity_node_id(fact.subject_entity_id)
        if fact.object_entity_id:
            target = entity_node_id(fact.object_entity_id)
        elif fact.case_id:
            target = case_node_id(fact.case_id)
        elif fact.event_id:
            target = event_node_id(fact.event_id)
        else:
            continue
        if source not in nodes or target not in nodes:
            continue
        edges.append(
            GraphEdge(
                id=f"fact:{fact.fact_id}",
                source=source,
                target=target,
                relationship_type=fact.predicate,
                classification="DIRECT",
                confidence=fact.confidence,
                provenance_kind="fact",
                fact_id=fact.fact_id,
                event_id=fact.event_id,
                case_id=fact.case_id,
                evidence_id=fact.evidence_id,
                created_at=fact.created_at.isoformat() if fact.created_at else None,
                updated_at=fact.updated_at.isoformat() if fact.updated_at else None,
            )
        )

    # --- Location hierarchy (Pune -> Maharashtra -> India) ---
    for location in locations.values():
        if location.parent_location_id is None:
            continue
        parent = locations.get(location.parent_location_id)
        if parent is None:
            continue
        edges.append(
            GraphEdge(
                id=f"loc-parent:{location.location_id}",
                source=entity_node_id(location.entity_id),
                target=entity_node_id(parent.entity_id),
                relationship_type="LOCATED_IN",
                classification="DIRECT",
                provenance_kind="location_parent",
            )
        )

    return nodes, edges
