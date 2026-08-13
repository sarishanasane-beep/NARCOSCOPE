from typing import Any

from pydantic import BaseModel


class GraphNodeOut(BaseModel):
    id: str
    name: str
    node_kind: str  # entity | event | case
    type: str       # PERSON / ORGANIZATION / LOCATION / EVENT / CASE / ...
    status: str
    aliases: list[str] = []
    entity_id: str | None = None
    event_id: str | None = None
    case_id: str | None = None
    event_type: str | None = None
    date_precision: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    case_number: str | None = None
    jurisdiction: str | None = None
    # Structured-source semantics (entities only) preserved at
    # confirmation: CONTEXTUAL / MENTIONED_ONLY / ACCUSED / ...
    investigative_status: str | None = None
    mention_context: str | None = None
    role: str | None = None
    # Source document id (entities/events) for source-document details.
    document_id: str | None = None


class GraphEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: str
    classification: str
    confidence: float | None = None
    provenance_kind: str  # relationship | fact | event_case | event_location | location_parent
    relationship_id: str | None = None
    fact_id: str | None = None
    event_id: str | None = None
    case_id: str | None = None
    evidence_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class GraphResponse(BaseModel):
    center: GraphNodeOut
    nodes: list[GraphNodeOut] = []
    edges: list[GraphEdgeOut] = []
    # Exploration metadata (Prompt 2 Part 2): hop depth of the returned
    # subgraph and whether the node limit truncated the result set.
    hops: int = 1
    total_found: int = 0
    truncated: bool = False


class GraphStats(BaseModel):
    total_nodes: int
    total_edges: int
    nodes_by_type: dict[str, int]
    edges_by_type: dict[str, int]
    # Analysis scope: "case" when case_id is provided, otherwise "global".
    scope: str | None = None
    case_id: str | None = None


class GraphProvenanceOut(BaseModel):
    edge_kind: str
    edge_id: str
    relationship_type: str
    classification: str | None = None
    relationship: dict[str, Any] | None = None
    fact: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    case: dict[str, Any] | None = None
    location: dict[str, Any] | None = None
    parent: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    document: dict[str, Any] | None = None
    source: dict[str, Any] | None = None
    # Endpoint names/types of the confirmed relationship (or fact subject).
    source_name: str | None = None
    source_type: str | None = None
    target_name: str | None = None
    target_type: str | None = None
