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
from app.models.entity import ENTITY_STATUS_ACTIVE, ENTITY_STATUS_MERGED, Entity
from app.models.event import Event
from app.models.location import Location
from app.services.graph.builder import _event_node, build_trusted_graph
from app.services.graph.model import (
    GraphNode,
    case_node_id,
    entity_node_id,
    event_node_id,
)
from app.utils.errors import NotFoundError


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

    def stats(self, db: Session, case_id: str | None = None) -> dict[str, Any]:
        """Trusted graph counts by node/edge type.

        Pass ``case_id`` to scope the statistics to ONE case — the stats
        then reflect only that case's trusted graph (no global mixing).
        """
        if case_id:
            payload = self.get_case_graph_full(db, case_id)
            if payload is None:
                raise NotFoundError("Case not found.")
            nodes = payload["nodes"]
            edges = payload["edges"]
            nodes_by_type: Counter[str] = Counter(
                n.get("type", "OTHER") for n in nodes
            )
            edges_by_type: Counter[str] = Counter(
                e.get("relationship_type", "UNKNOWN") for e in edges
            )
            return {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "nodes_by_type": dict(sorted(nodes_by_type.items())),
                "edges_by_type": dict(sorted(edges_by_type.items())),
                "scope": "case",
                "case_id": case_id,
            }
        graph = self.build(db)
        nodes_by_type = Counter(graph.nodes[n].get("type", "OTHER") for n in graph.nodes)
        edges_by_type = Counter(
            graph.edges[u, v, k].get("relationship_type", "UNKNOWN")
            for u, v, k in graph.edges(keys=True)
        )
        return {
            "total_nodes": graph.number_of_nodes(),
            "total_edges": graph.number_of_edges(),
            "nodes_by_type": dict(sorted(nodes_by_type.items())),
            "edges_by_type": dict(sorted(edges_by_type.items())),
            "scope": "global",
        }

    # ------------------------------------------------------------------
    # Location network (case-scoped, trusted data only)
    # ------------------------------------------------------------------

    def get_case_locations(self, db: Session, case_id: str) -> dict[str, Any] | None:
        """Location-focused view of ONE case's trusted graph.

        Only explicit trusted data: location nodes, location-related
        relationship edges, and events with an explicit location link.
        Proximity / same-city / same-district inference is NEVER applied.
        """
        payload = self.get_case_graph_full(db, case_id)
        if payload is None:
            return None
        nodes = payload["nodes"]
        edges = payload["edges"]
        by_id = {n["id"]: n for n in nodes}
        location_nodes = [n for n in nodes if n.get("type") == "LOCATION"]
        location_ids = {n["id"] for n in location_nodes}
        # An explicit location relationship touches at least one location
        # node and is NOT a derived event->location edge (those are shown
        # as "events with locations" instead).
        location_edges = [
            e for e in edges
            if e.get("provenance_kind") == "relationship"
            and (e.get("source") in location_ids or e.get("target") in location_ids)
        ]
        event_location_edges = [
            e for e in edges
            if e.get("provenance_kind") == "event_location"
        ]
        events_with_locations: list[dict[str, Any]] = []
        for e in event_location_edges:
            event = by_id.get(e.get("source"))
            location = by_id.get(e.get("target"))
            if event and location:
                events_with_locations.append({
                    "event_id": event.get("event_id"),
                    "event_name": event.get("name"),
                    "event_type": event.get("type"),
                    "location_id": location.get("entity_id"),
                    "location_name": location.get("name"),
                })
        return {
            "scope": "case",
            "case_id": case_id,
            "total_locations": len(location_nodes),
            "total_location_relationships": len(location_edges),
            "total_events_with_locations": len(events_with_locations),
            "locations": location_nodes,
            "location_relationships": location_edges,
            "events_with_locations": events_with_locations,
        }

    @staticmethod
    def _entity_center(entity: Entity) -> GraphNode:
        aliases: list[str] = []
        if entity.person is not None:
            aliases = list(entity.person.aliases or [])
        elif entity.organization is not None:
            aliases = list(entity.organization.aliases or [])
        meta = entity.structured_metadata or {}
        return GraphNode(
            id=entity_node_id(entity.entity_id),
            name=entity.canonical_name,
            node_kind="entity",
            type=entity.entity_type,
            status=entity.status,
            aliases=aliases,
            entity_id=entity.entity_id,
            investigative_status=meta.get("investigative_status"),
            mention_context=meta.get("mention_context"),
            role=meta.get("role"),
            document_id=entity.document_id,
        )

    # ------------------------------------------------------------------
    # Case-scoped full graph
    # ------------------------------------------------------------------

    def get_case_graph_full(self, db: Session, case_id: str) -> dict[str, Any] | None:
        """The COMPLETE trusted graph belonging to one case.

        Membership is derived from trusted records only (never fabricated):
          - events with ``case_id``
          - confirmed relationships with ``case_id`` (or linked to one of
            the case's events)
          - endpoints of those relationships
          - entities whose source document produced the case (this is how
            isolated / mentioned-only entities stay visible: they belong
            to the case document even though they have zero edges)
        """
        case = db.get(Case, case_id)
        if case is None:
            return None
        from sqlalchemy import or_

        from app.models.document import Document
        from app.models.relationship import REL_STATUS_CONFIRMED, Relationship

        # One structured document = one case: the documents anchored to the
        # case are the source of truth for membership.
        case_documents = db.query(Document).filter(Document.case_id == case_id).all()
        document_ids = {doc.document_id for doc in case_documents if doc.document_id}
        case_events = (
            db.query(Event)
            .filter(or_(Event.case_id == case_id, Event.document_id.in_(document_ids)))
            .all()
        )
        event_ids = {event.event_id for event in case_events}
        document_ids |= {event.document_id for event in case_events if event.document_id}

        # A confirmed relationship belongs to the case when its supporting
        # evidence comes from one of the case's documents (confirmation
        # order independent) or it is directly linked to the case.
        if document_ids:
            from app.models.evidence import Evidence

            evidence_ids = {
                ev.evidence_id
                for ev in db.query(Evidence)
                .filter(Evidence.document_id.in_(document_ids))
                .all()
            }
        else:
            evidence_ids = set()
        relationships = (
            db.query(Relationship)
            .filter(
                Relationship.status == REL_STATUS_CONFIRMED,
                or_(
                    Relationship.case_id == case_id,
                    Relationship.evidence_id.in_(evidence_ids),
                ),
            )
            .all()
        )
        # Relationships attached to one of the case's events (an empty set
        # matches nothing — `IN (NULL)` is false in SQL).
        event_relationships = (
            db.query(Relationship)
            .filter(
                Relationship.status == REL_STATUS_CONFIRMED,
                Relationship.event_id.in_(event_ids),
            )
            .all()
        )
        # Merge by id — a relationship may match both conditions.
        rel_by_id: dict[str, Any] = {}
        for rel in relationships + event_relationships:
            rel_by_id.setdefault(rel.relationship_id, rel)
        rels = list(rel_by_id.values())

        nodes: dict[str, GraphNode] = {}
        edges: list[dict[str, Any]] = []

        def _edge(
            edge_id: str, source: str, target: str, rel_type: str,
            classification: str = "DIRECT", provenance_kind: str = "relationship",
            relationship_id: str | None = None, event_id: str | None = None,
            case_ref: str | None = None,
        ) -> dict[str, Any]:
            return {
                "id": edge_id,
                "source": source,
                "target": target,
                "relationship_type": rel_type,
                "classification": classification,
                "provenance_kind": provenance_kind,
                "relationship_id": relationship_id,
                "event_id": event_id,
                "case_id": case_ref,
            }

        # Case node is the logical root/center.
        nodes[case_node_id(case_id)] = GraphNode(
            id=case_node_id(case_id),
            name=case.case_name or case.official_case_number or f"Case {case_id[:8]}",
            node_kind="case",
            type="CASE",
            status=case.status or "UNKNOWN",
            case_id=case.case_id,
            case_number=case.official_case_number,
            jurisdiction=case.jurisdiction,
        )

        # One logical case node: a CASE-typed ENTITY row whose name matches
        # this case is the same logical object (endpoint records created
        # before case resolution existed). Two sources are remapped:
        #   - ACTIVE CASE-typed entities with the same normalized name
        #     (legacy duplicates),
        #   - entities explicitly reconciled into this case via
        #     Data Management (status MERGED + merged_into_case_id).
        # Their edges route to the case node so the graph never shows a
        # duplicate CASE node — the entity row stays as the FK target.
        from app.utils.text import normalize_name as _norm_name

        case_keys = {
            _norm_name(v) for v in (case.case_name, case.operation_name, case.official_case_number)
            if v
        }
        case_dup_ids: dict[str, str] = {}
        for dup in db.query(Entity).filter(Entity.entity_type == "CASE").all():
            if dup.status == ENTITY_STATUS_ACTIVE and _norm_name(dup.canonical_name) in case_keys:
                case_dup_ids[dup.entity_id] = case_node_id(case_id)
            elif (
                dup.status == ENTITY_STATUS_MERGED
                and dup.merged_into_case_id == case_id
            ):
                case_dup_ids[dup.entity_id] = case_node_id(case_id)

        # One canonical node per logical entity (REQ 17-19): entities from
        # the case's OWN documents are the canonical rows. A legacy row with
        # the same (entity_type, normalized canonical_name) — e.g. created
        # by older processing of a different document — is the same logical
        # entity. Relationship/event-location endpoints route to the
        # canonical node and the duplicate row is never emitted as a
        # separate node. Graph-view remap only (like case_dup_ids): the DB
        # rows stay untouched and no identity decision is made.
        canonical_rows: dict[tuple[str, str], Entity] = {}
        if document_ids:
            for _ent in db.query(Entity).filter(
                Entity.status == ENTITY_STATUS_ACTIVE,
                Entity.document_id.in_(document_ids),
            ).all():
                canonical_rows.setdefault(
                    (_ent.entity_type, _norm_name(_ent.canonical_name)), _ent
                )
        entity_remap: dict[str, Entity] = {}
        if canonical_rows:
            _endpoint_ids: set[str] = set()
            for _rel in rels:
                _endpoint_ids.add(_rel.source_entity_id)
                _endpoint_ids.add(_rel.target_entity_id)
            for _event in case_events:
                if _event.location_id:
                    _loc = db.get(Location, _event.location_id)
                    if _loc is not None and _loc.entity_id:
                        _endpoint_ids.add(_loc.entity_id)
            for _ent_id in _endpoint_ids:
                _ent = db.get(Entity, _ent_id)
                if _ent is None or _ent.status != ENTITY_STATUS_ACTIVE:
                    continue
                _key = (_ent.entity_type, _norm_name(_ent.canonical_name))
                _canon = canonical_rows.get(_key)
                if _canon is not None and _canon.entity_id != _ent.entity_id:
                    entity_remap[_ent.entity_id] = _canon

        def _resolve_endpoint(entity: Entity) -> tuple[GraphNode | None, str]:
            """Return (node to emit, edge endpoint id)."""
            canon = entity_remap.get(entity.entity_id)
            if canon is not None:
                node = self._entity_center(canon)
                return node, node.id
            node = self._entity_center(entity)
            endpoint = case_dup_ids.get(entity.entity_id, node.id)
            if endpoint == node.id:
                return node, node.id
            # Remapped to the canonical CASE node — never a separate node.
            return None, endpoint

        def _location_node(location: Location) -> GraphNode:
            ent = db.get(Entity, location.entity_id)
            canon = entity_remap.get(location.entity_id) if ent is not None else None
            if canon is not None:
                return self._entity_center(canon)
            if ent is not None:
                return self._entity_center(ent)
            return GraphNode(
                id=entity_node_id(location.entity_id),
                name=location.canonical_name,
                node_kind="entity",
                type="LOCATION",
                status="ACTIVE",
                entity_id=location.entity_id,
            )

        # Events of the case (+ event->case edges).
        for event in case_events:
            node = _event_node(event)
            nodes[node.id] = node
            edges.append(_edge(
                f"ev-case:{event.event_id}:{case_id}", node.id, case_node_id(case_id),
                "PART_OF", provenance_kind="event_case", event_id=event.event_id, case_ref=case_id,
            ))
            if event.location_id:
                location = db.get(Location, event.location_id)
                if location is not None:
                    loc_node = _location_node(location)
                    nodes[loc_node.id] = loc_node
                    edges.append(_edge(
                        f"ev-loc:{event.event_id}:{location.location_id}", node.id, loc_node.id,
                        "OCCURRED_IN", provenance_kind="event_location", event_id=event.event_id,
                    ))

        # Confirmed relationships of the case.
        for rel in rels:
            source = db.get(Entity, rel.source_entity_id)
            target = db.get(Entity, rel.target_entity_id)
            if source is None or target is None:
                continue
            src_node, src_id = _resolve_endpoint(source)
            tgt_node, tgt_id = _resolve_endpoint(target)
            if src_node is not None:
                nodes[src_node.id] = src_node
            if tgt_node is not None:
                nodes[tgt_node.id] = tgt_node
            edges.append(_edge(
                rel.relationship_id, src_id, tgt_id,
                rel.relationship_type, classification=rel.classification or "DIRECT",
                provenance_kind="relationship", relationship_id=rel.relationship_id,
                event_id=rel.event_id, case_ref=case_id,
            ))
            if rel.event_id and rel.event_id in event_ids:
                event_node = event_node_id(rel.event_id)
                if event_node in nodes:
                    edges.append(_edge(
                        f"ev-rel:{rel.relationship_id}", event_node, src_node.id if src_node else src_id,
                        "EVENT_INVOLVES", classification="DIRECT", provenance_kind="event_relationship",
                        relationship_id=rel.relationship_id, event_id=rel.event_id,
                    ))

        # Isolated / mentioned-only entities: they belong to the case via
        # their source document — shown as nodes, never connected by
        # fabricated edges.
        if document_ids:
            for entity in (
                db.query(Entity)
                .filter(
                    Entity.status == ENTITY_STATUS_ACTIVE,
                    Entity.merged_into_id.is_(None),
                    Entity.document_id.in_(document_ids),
                )
                .all()
            ):
                if entity.entity_id in case_dup_ids:
                    continue  # same logical object as the case node
                node = self._entity_center(entity)
                nodes.setdefault(node.id, node)

        entity_count = sum(1 for n in nodes.values() if n.node_kind == "entity")
        return {
            "center": nodes[case_node_id(case_id)].to_dict(),
            "nodes": [n.to_dict() for n in nodes.values()],
            "edges": edges,
            "hops": "full",
            "total_found": len(nodes),
            "truncated": False,
            "entities_total": entity_count,
            "relationships_total": len(rels),
            "events_total": len(case_events),
            "document_ids": sorted(d for d in document_ids if d),
            "case": {
                "case_id": case.case_id,
                "case_name": case.case_name,
                "official_case_number": case.official_case_number,
                "category": case.category,
                "status": case.status,
                "description": case.description,
                "jurisdiction": case.jurisdiction,
            },
        }


# Module-level singleton used by the API routes.
graph_service = NetworkXGraphService()
