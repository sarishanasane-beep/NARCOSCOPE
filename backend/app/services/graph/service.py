"""Graph service abstraction.

``GraphService`` defines the operations the investigation API needs;
``NetworkXGraphService`` implements them with NetworkX over the trusted
database. The abstraction keeps the API independent of the graph backend
(a future Neo4jGraphService could replace it without touching routes).

The graph is ALWAYS reconstructed from the trusted database on demand —
the NetworkX object is a derived view, never the source of truth. If the
application restarts, the graph is rebuilt from confirmed rows.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from typing import Any

import networkx as nx
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.entity import Entity
from app.models.event import Event
from app.models.location import Location
from app.services.graph.builder import build_trusted_graph
from app.services.graph.model import (
    GraphNode,
    case_node_id,
    entity_node_id,
    event_node_id,
)


class GraphService(ABC):
    """Operations the investigation API needs from the knowledge graph."""

    @abstractmethod
    def build(self, db: Session):  # pragma: no cover - interface
        """Build the full trusted graph (NetworkX object)."""

    @abstractmethod
    def rebuild(self, db: Session):  # pragma: no cover - interface
        """Rebuild the trusted graph from the database."""

    @abstractmethod
    def get_entity_graph(self, db: Session, entity_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def get_case_graph(self, db: Session, case_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def get_event_graph(self, db: Session, event_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def get_location_graph(self, db: Session, location_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def stats(self, db: Session) -> dict[str, Any]: ...


class NetworkXGraphService(GraphService):
    """NetworkX-backed trusted graph service."""

    def build(self, db: Session) -> nx.MultiDiGraph:
        nodes, edges = build_trusted_graph(db)
        graph = nx.MultiDiGraph()
        for node in nodes.values():
            graph.add_node(node.id, **node.to_dict())
        for edge in edges:
            graph.add_edge(edge.source, edge.target, key=edge.id, **edge.to_dict())
        return graph

    def rebuild(self, db: Session) -> nx.MultiDiGraph:
        # The graph is derived state: rebuilding is identical to building.
        # Caching is intentionally deferred so results always mirror the
        # current trusted database state (rule: DB is the source of truth).
        return self.build(db)

    # ------------------------------------------------------------------
    # Bounded subgraphs (1-hop / 2-hop exploration)
    # ------------------------------------------------------------------

    def _subgraph(
        self,
        db: Session,
        center_id: str,
        *,
        hops: int = 1,
        limit: int = 100,
        relationship_type: str | None = None,
        entity_type: str | None = None,
        case_id: str | None = None,
    ) -> tuple[GraphNode | None, list[dict[str, Any]], list[dict[str, Any]], int, bool]:
        """Bounded subgraph around ``center_id``.

        Returns ``(center, nodes, edges, total_found, truncated)``.
        Nodes are ranked by graph degree (most connected first) so the
        most relevant subset survives the node limit.
        """
        graph = self.build(db)
        hops = max(1, min(int(hops or 1), 3))
        limit = max(1, min(int(limit or 100), 500))
        center: GraphNode | None = None
        if center_id in graph:
            center = GraphNode(**{k: v for k, v in graph.nodes[center_id].items()})
        if center is None:
            return None, [], [], 0, False
        frontier = {center_id}
        node_ids = {center_id}
        for _ in range(hops):
            nxt: set[str] = set()
            for node in frontier:
                for nbr in graph.successors(node):
                    nxt.add(nbr)
                for nbr in graph.predecessors(node):
                    nxt.add(nbr)
            node_ids |= nxt
            frontier = nxt
        if entity_type:
            node_ids = {
                n for n in node_ids
                if n in graph.nodes and graph.nodes[n].get("type") == entity_type
            }
            node_ids.add(center_id)
        nodes_data = [dict(graph.nodes[n]) for n in node_ids if n in graph.nodes]
        edge_pool = [
            dict(graph.edges[u, v, k])
            for u, v, k in graph.edges(keys=True)
            if u in node_ids and v in node_ids
        ]
        if relationship_type:
            edge_pool = [e for e in edge_pool if e.get("relationship_type") == relationship_type]
        if case_id:
            edge_pool = [e for e in edge_pool if e.get("case_id") == case_id]
        total_found = len(nodes_data)
        truncated = total_found > limit
        nodes_data.sort(key=lambda d: (-graph.degree(d["id"]), d.get("name", "")))
        kept = {d["id"] for d in nodes_data[:limit]}
        kept.add(center_id)
        nodes = [d for d in nodes_data if d["id"] in kept]
        edges = [e for e in edge_pool if e["source"] in kept and e["target"] in kept]
        return center, nodes, edges, total_found, truncated

    def get_entity_graph(
        self,
        db: Session,
        entity_id: str,
        *,
        hops: int = 1,
        limit: int = 100,
        relationship_type: str | None = None,
        entity_type: str | None = None,
        case_id: str | None = None,
    ) -> dict[str, Any] | None:
        entity = db.get(Entity, entity_id)
        if entity is None:
            return None
        center, nodes, edges, total_found, truncated = self._subgraph(
            db, entity_node_id(entity_id), hops=hops, limit=limit,
            relationship_type=relationship_type, entity_type=entity_type, case_id=case_id,
        )
        if center is None:
            # The entity record exists but is not part of the trusted graph
            # (e.g. non-ACTIVE status) — return the entity alone.
            center = self._entity_center(entity)
            nodes, edges = [], []
            total_found, truncated = 0, False
        return {
            "center": center.to_dict(),
            "nodes": nodes,
            "edges": edges,
            "hops": hops,
            "total_found": total_found,
            "truncated": truncated,
        }

    def get_case_graph(
        self,
        db: Session,
        case_id: str,
        *,
        hops: int = 1,
        limit: int = 100,
        relationship_type: str | None = None,
        entity_type: str | None = None,
    ) -> dict[str, Any] | None:
        if db.get(Case, case_id) is None:
            return None
        center, nodes, edges, total_found, truncated = self._subgraph(
            db, case_node_id(case_id), hops=hops, limit=limit,
            relationship_type=relationship_type, entity_type=entity_type,
        )
        if center is None:
            return None
        return {
            "center": center.to_dict(),
            "nodes": nodes,
            "edges": edges,
            "hops": hops,
            "total_found": total_found,
            "truncated": truncated,
        }

    def get_event_graph(
        self,
        db: Session,
        event_id: str,
        *,
        hops: int = 1,
        limit: int = 100,
        relationship_type: str | None = None,
        entity_type: str | None = None,
    ) -> dict[str, Any] | None:
        if db.get(Event, event_id) is None:
            return None
        center, nodes, edges, total_found, truncated = self._subgraph(
            db, event_node_id(event_id), hops=hops, limit=limit,
            relationship_type=relationship_type, entity_type=entity_type,
        )
        if center is None:
            return None
        return {
            "center": center.to_dict(),
            "nodes": nodes,
            "edges": edges,
            "hops": hops,
            "total_found": total_found,
            "truncated": truncated,
        }

    def get_location_graph(
        self,
        db: Session,
        location_id: str,
        *,
        hops: int = 1,
        limit: int = 100,
        relationship_type: str | None = None,
        entity_type: str | None = None,
    ) -> dict[str, Any] | None:
        location = db.get(Location, location_id)
        if location is None:
            return None
        return self.get_entity_graph(
            db, location.entity_id, hops=hops, limit=limit,
            relationship_type=relationship_type, entity_type=entity_type,
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self, db: Session) -> dict[str, Any]:
        graph = self.build(db)
        nodes_by_type: Counter[str] = Counter(
            graph.nodes[n].get("type", "OTHER") for n in graph.nodes
        )
        edges_by_type: Counter[str] = Counter(
            graph.edges[u, v, k].get("relationship_type", "UNKNOWN")
            for u, v, k in graph.edges(keys=True)
        )
        return {
            "total_nodes": graph.number_of_nodes(),
            "total_edges": graph.number_of_edges(),
            "nodes_by_type": dict(sorted(nodes_by_type.items())),
            "edges_by_type": dict(sorted(edges_by_type.items())),
        }

    @staticmethod
    def _entity_center(entity: Entity) -> GraphNode:
        aliases: list[str] = []
        if entity.person is not None:
            aliases = list(entity.person.aliases or [])
        elif entity.organization is not None:
            aliases = list(entity.organization.aliases or [])
        return GraphNode(
            id=entity_node_id(entity.entity_id),
            name=entity.canonical_name,
            node_kind="entity",
            type=entity.entity_type,
            status=entity.status,
            aliases=aliases,
            entity_id=entity.entity_id,
        )


# Module-level singleton used by the API routes.
graph_service = NetworkXGraphService()
