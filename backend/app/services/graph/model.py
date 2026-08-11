"""Trusted master knowledge graph — node/edge models.

These dataclasses serialize to the dicts consumed by the graph API and
the frontend. They carry enough identity + provenance metadata to render
investigation views without duplicating entire database records (IDs are
kept so the UI/API can fetch full details from the database).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


def entity_node_id(entity_id: str) -> str:
    return f"entity:{entity_id}"


def event_node_id(event_id: str) -> str:
    return f"event:{event_id}"


def case_node_id(case_id: str) -> str:
    return f"case:{case_id}"


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@dataclass
class GraphNode:
    """A trusted node: entity, event or case.

    ``node_kind`` is one of ``entity`` | ``event`` | ``case``; ``type`` is
    the semantic type (PERSON / ORGANIZATION / LOCATION / EVENT / CASE /
    OTHER ...) used for coloring and categorization.
    """

    id: str
    name: str
    node_kind: str
    type: str
    status: str
    aliases: list[str] = field(default_factory=list)
    entity_id: str | None = None
    event_id: str | None = None
    case_id: str | None = None
    event_type: str | None = None
    date_precision: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    case_number: str | None = None
    jurisdiction: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "node_kind": self.node_kind,
            "type": self.type,
            "status": self.status,
            "aliases": list(self.aliases or []),
            "entity_id": self.entity_id,
            "event_id": self.event_id,
            "case_id": self.case_id,
            "event_type": self.event_type,
            "date_precision": self.date_precision,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "case_number": self.case_number,
            "jurisdiction": self.jurisdiction,
        }


@dataclass
class GraphEdge:
    """A trusted edge with full provenance metadata.

    ``provenance_kind`` is one of:
      relationship | fact | event_case | event_location | location_parent

    The evidence/case/event IDs let the investigator explain WHY a
    connection exists (GRAPH EDGE -> TRUSTED RECORD -> EVIDENCE ->
    SOURCE -> DOCUMENT).
    """

    id: str
    source: str
    target: str
    relationship_type: str
    classification: str
    confidence: float | None = None
    provenance_kind: str = "relationship"
    relationship_id: str | None = None
    fact_id: str | None = None
    event_id: str | None = None
    case_id: str | None = None
    evidence_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relationship_type": self.relationship_type,
            "classification": self.classification,
            "confidence": self.confidence,
            "provenance_kind": self.provenance_kind,
            "relationship_id": self.relationship_id,
            "fact_id": self.fact_id,
            "event_id": self.event_id,
            "case_id": self.case_id,
            "evidence_id": self.evidence_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
