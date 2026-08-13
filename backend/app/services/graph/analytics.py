"""Trusted graph analytics (Prompt 2 Part 2).

Deterministic NetworkX algorithms over the TRUSTED graph only:

  - degree centrality / betweenness centrality (normalized)
  - connected components
  - shortest path between trusted entities
  - community/cluster detection (greedy modularity)

Candidate data (PENDING / REJECTED / EDITED / POSSIBLE_MATCH) never
influences these calculations — the graph is built by
``build_trusted_graph`` from confirmed records exclusively.

Neutral terminology is used for clusters ("Network Cluster N") — a
cluster is NEVER labeled criminal/gang/guilty unless the database
explicitly contains an official documented designation.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import networkx as nx
from sqlalchemy.orm import Session

from app.services.graph.builder import build_trusted_graph
from app.services.graph.model import entity_node_id
from app.utils.errors import NotFoundError


def _simple_graph(db: Session, case_id: str | None = None) -> nx.Graph:
    """Undirected simple graph (parallel edges collapsed) for analytics.

    When ``case_id`` is provided the graph is built from the CASE-SCOPED
    trusted graph (``get_case_graph_full``) — analytics never silently mix
    other cases / unrelated records into the selected case's analysis
    (REQ: case-scoped statistics). Merged/superseded records are already
    excluded by the graph builder.
    """
    if case_id:
        from app.services.graph.service import graph_service

        payload = graph_service.get_case_graph_full(db, case_id)
        if payload is None:
            raise NotFoundError("Case not found.")
        graph = nx.Graph()
        for node in payload["nodes"]:
            graph.add_node(node["id"], **node)
        for edge in payload["edges"]:
            if edge.get("source") == edge.get("target"):
                continue
            if not graph.has_edge(edge["source"], edge["target"]):
                graph.add_edge(edge["source"], edge["target"], **edge)
        return graph

    nodes, edges = build_trusted_graph(db)
    graph = nx.Graph()
    for node in nodes.values():
        graph.add_node(node.id, **node.to_dict())
    for edge in edges:
        if not graph.has_edge(edge.source, edge.target):
            graph.add_edge(edge.source, edge.target, **edge.to_dict())
    graph.remove_edges_from(nx.selfloop_edges(graph))
    return graph


def degree_centrality(db: Session, case_id: str | None = None) -> dict[str, float]:
    """Normalized degree centrality (0..1) for every trusted node."""
    return nx.degree_centrality(_simple_graph(db, case_id=case_id))


def betweenness_centrality(db: Session, case_id: str | None = None) -> dict[str, float]:
    """Normalized betweenness centrality (0..1) for every trusted node."""
    return nx.betweenness_centrality(_simple_graph(db, case_id=case_id))


def connected_components(db: Session, case_id: str | None = None) -> list[dict[str, Any]]:
    """Connected components of the trusted graph with aggregate info."""
    graph = _simple_graph(db, case_id=case_id)
    result: list[dict[str, Any]] = []
    for i, component in enumerate(nx.connected_components(graph), start=1):
        sub = graph.subgraph(component)
        types = Counter(sub.nodes[n].get("type", "OTHER") for n in sub.nodes)
        result.append(
            {
                "component_id": i,
                "node_count": sub.number_of_nodes(),
                "edge_count": sub.number_of_edges(),
                "dominant_entity_types": dict(types.most_common()),
                "nodes": [dict(sub.nodes[n]) for n in sub.nodes],
            }
        )
    return result


def _cluster_communities(db: Session, case_id: str | None = None) -> list[frozenset]:
    """Communities sorted by size (largest first). Empty graph -> []."""
    graph = _simple_graph(db, case_id=case_id)
    if graph.number_of_nodes() == 0:
        return []
    communities = nx.community.greedy_modularity_communities(graph)
    return sorted(communities, key=len, reverse=True)


def detect_clusters(db: Session, case_id: str | None = None) -> list[dict[str, Any]]:
    """Network clusters with stats.

    Each cluster: node/edge counts, dominant entity types, associated
    cases/events, geographic distribution (location nodes) and growth
    over time (edges grouped by year of created_at).

    Pass ``case_id`` to scope the analysis to one case — clusters never
    mix data from other cases into the selected case's analysis.
    """
    graph = _simple_graph(db, case_id=case_id)
    communities = _cluster_communities(db, case_id=case_id)
    out: list[dict[str, Any]] = []
    for i, community in enumerate(communities, start=1):
        nodes = [dict(graph.nodes[n]) for n in community]
        edges = [
            dict(data) for u, v, data in graph.edges(data=True)
            if u in community and v in community
        ]
        types = Counter(n.get("type", "OTHER") for n in nodes)
        cases: set[str] = {
            n.get("case_id") for n in nodes
            if n.get("node_kind") == "case" and n.get("case_id")
        }
        cases |= {e.get("case_id") for e in edges if e.get("case_id")}
        events: set[str] = {
            n.get("event_id") for n in nodes
            if n.get("node_kind") == "event" and n.get("event_id")
        }
        events |= {e.get("event_id") for e in edges if e.get("event_id")}
        locations = sorted({n.get("name") for n in nodes if n.get("type") == "LOCATION"})
        growth: Counter[str] = Counter()
        for e in edges:
            created = e.get("created_at") or ""
            if created:
                growth[created[:4]] += 1
        out.append(
            {
                "cluster_id": i,
                "label": f"Network Cluster {i}",
                "node_count": len(nodes),
                "edge_count": len(edges),
                "dominant_entity_types": dict(types.most_common()),
                "associated_cases": sorted(cases),
                "associated_events": sorted(events),
                "geographic_distribution": locations,
                "growth_over_time": dict(sorted(growth.items())),
            }
        )
    return out


def cluster_membership(db: Session, case_id: str | None = None) -> dict[str, int]:
    """node id -> cluster number (1..N) for trusted graph nodes.

    Nodes not placed in any community are omitted; callers treat them as
    unclustered (cross-cluster score 0).
    """
    communities = _cluster_communities(db, case_id=case_id)
    mapping: dict[str, int] = {}
    for i, community in enumerate(communities, start=1):
        for node in community:
            mapping[node] = i
    return mapping


def shortest_path(
    db: Session, source_entity_id: str, target_entity_id: str
) -> dict[str, Any]:
    """Shortest trusted path between two entities.

    Returns node + edge metadata for every hop. Paths never traverse
    candidate relationships — the graph only contains confirmed rows.
    """
    graph = _simple_graph(db)
    source = entity_node_id(source_entity_id)
    target = entity_node_id(target_entity_id)
    if source not in graph:
        raise NotFoundError("Source entity not found in the trusted graph.")
    if target not in graph:
        raise NotFoundError("Target entity not found in the trusted graph.")
    try:
        path = nx.shortest_path(graph, source, target)
    except nx.NetworkXNoPath:
        return {
            "distance": None,
            "connected": False,
            "path": [],
            "edges": [],
        }
    nodes = [dict(graph.nodes[n]) for n in path]
    edges: list[dict[str, Any]] = []
    for u, v in zip(path, path[1:]):
        data = graph.get_edge_data(u, v)
        if not data:
            continue
        # For a simple nx.Graph, get_edge_data returns the attribute dict
        # directly ({source, target, relationship_type, ...}). For a
        # MultiGraph it returns {key: attrs} — normalize both to the attrs.
        first_key = next(iter(data))
        attr = data if isinstance(first_key, str) else data[first_key]
        edges.append(attr)
    return {
        "distance": len(path) - 1,
        "connected": True,
        "path": nodes,
        "edges": edges,
    }
