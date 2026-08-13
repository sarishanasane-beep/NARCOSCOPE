"""Trusted knowledge graph API (Prompt 2 Part 1 + Part 2).

All endpoints return real database-backed graph information derived
exclusively from confirmed/trusted records. PENDING / REJECTED /
CANDIDATE / POSSIBLE_MATCH information never appears here.

Part 2 additions: 1-hop/2-hop exploration with a node limit and filters
(relationship type, entity type, case), plus analytics (centrality,
components, clusters, shortest path).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.graph import GraphProvenanceOut, GraphResponse, GraphStats
from app.services.graph.analytics import (
    betweenness_centrality,
    connected_components,
    degree_centrality,
    detect_clusters,
    shortest_path,
)
from app.services.graph.provenance import edge_provenance
from app.services.graph.service import graph_service
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/stats", response_model=GraphStats)
def graph_stats(case_id: str | None = None, db: Session = Depends(get_db)) -> GraphStats:
    """Overview counts for the trusted graph (nodes/edges by type).

    Pass ``case_id`` to scope the statistics to ONE case — analytics then
    reflect only that case's trusted graph, never other cases or
    unrelated records.
    """
    return GraphStats(**graph_service.stats(db, case_id=case_id))


@router.get("/analytics/centrality")
def graph_centrality(case_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Normalized degree + betweenness centrality for trusted nodes.

    ``case_id`` scopes the calculation to one case's trusted graph.
    """
    return {
        "degree": degree_centrality(db, case_id=case_id),
        "betweenness": betweenness_centrality(db, case_id=case_id),
    }


@router.get("/analytics/components")
def graph_components(case_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Connected components of the trusted graph.

    ``case_id`` scopes the components to one case.
    """
    components = connected_components(db, case_id=case_id)
    return {"total": len(components), "components": components}


@router.get("/analytics/clusters")
def graph_clusters(case_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Network clusters (neutral terminology) with aggregate stats.

    ``case_id`` scopes the clusters to one case.
    """
    clusters = detect_clusters(db, case_id=case_id)
    return {"total": len(clusters), "clusters": clusters}


@router.get("/path")
def graph_path(
    source: str, target: str, db: Session = Depends(get_db)
) -> dict:
    """Shortest trusted path between two entities (never via candidates)."""
    return shortest_path(db, source, target)


@router.get("/entity/{entity_id}", response_model=GraphResponse)
def entity_graph(
    entity_id: str,
    hops: int = 1,
    limit: int = 100,
    relationship_type: str | None = None,
    entity_type: str | None = None,
    case_id: str | None = None,
    db: Session = Depends(get_db),
) -> GraphResponse:
    """Trusted graph around an entity (person, org, location, ...).

    ``hops``: 1 (direct connections) or 2 (indirect connections — never
    labeled as direct). ``limit`` caps the visible node set; larger graphs
    report ``truncated`` with ``total_found``.
    """
    payload = graph_service.get_entity_graph(
        db, entity_id, hops=hops, limit=limit,
        relationship_type=relationship_type, entity_type=entity_type, case_id=case_id,
    )
    if payload is None:
        raise NotFoundError("Entity not found.")
    return GraphResponse(**payload)


@router.get("/case/{case_id}", response_model=GraphResponse)
def case_graph(
    case_id: str,
    hops: int = 1,
    limit: int = 100,
    relationship_type: str | None = None,
    entity_type: str | None = None,
    db: Session = Depends(get_db),
) -> GraphResponse:
    """Trusted graph around a case (supports 1/2-hop exploration)."""
    payload = graph_service.get_case_graph(
        db, case_id, hops=hops, limit=limit,
        relationship_type=relationship_type, entity_type=entity_type,
    )
    if payload is None:
        raise NotFoundError("Case not found.")
    return GraphResponse(**payload)


@router.get("/case/{case_id}/full")
def case_graph_full(
    case_id: str, db: Session = Depends(get_db)
) -> dict:
    """The COMPLETE trusted graph belonging to one case.

    Default view for the case-centric Network Explorer: every trusted
    entity, event and confirmed relationship of the case, including
    isolated / mentioned-only entities that belong to the case document
    (never connected by fabricated edges). Filtering is a separate view
    operation on this payload.
    """
    payload = graph_service.get_case_graph_full(db, case_id)
    if payload is None:
        raise NotFoundError("Case not found.")
    return payload


@router.get("/event/{event_id}", response_model=GraphResponse)
def event_graph(
    event_id: str,
    hops: int = 1,
    limit: int = 100,
    relationship_type: str | None = None,
    entity_type: str | None = None,
    db: Session = Depends(get_db),
) -> GraphResponse:
    """Trusted graph around an event (supports 1/2-hop exploration)."""
    payload = graph_service.get_event_graph(
        db, event_id, hops=hops, limit=limit,
        relationship_type=relationship_type, entity_type=entity_type,
    )
    if payload is None:
        raise NotFoundError("Event not found.")
    return GraphResponse(**payload)


@router.get("/location/{location_id}", response_model=GraphResponse)
def location_graph(
    location_id: str,
    hops: int = 1,
    limit: int = 100,
    relationship_type: str | None = None,
    entity_type: str | None = None,
    db: Session = Depends(get_db),
) -> GraphResponse:
    """Trusted graph around a location (by Location id)."""
    payload = graph_service.get_location_graph(
        db, location_id, hops=hops, limit=limit,
        relationship_type=relationship_type, entity_type=entity_type,
    )
    if payload is None:
        raise NotFoundError("Location not found.")
    return GraphResponse(**payload)


@router.get("/case/{case_id}/locations")
def case_locations(case_id: str, db: Session = Depends(get_db)) -> dict:
    """Location-focused analytical view of ONE case (trusted data only).

    Returns the case's location nodes, explicit location-related
    relationship edges, and events with an explicit location link. No
    proximity / same-city / same-district inference is ever applied.
    """
    payload = graph_service.get_case_locations(db, case_id)
    if payload is None:
        raise NotFoundError("Case not found.")
    return payload


@router.get("/provenance/{edge_kind}/{edge_id}", response_model=GraphProvenanceOut)
def graph_provenance(
    edge_kind: str, edge_id: str, db: Session = Depends(get_db)
) -> GraphProvenanceOut:
    """Explain why a trusted graph edge exists.

    ``edge_kind``: relationship | fact | event_case | event_location | location_parent
    Resolves: trusted record -> evidence -> document -> source.
    """
    payload = edge_provenance(db, edge_kind, edge_id)
    return GraphProvenanceOut(**payload)
