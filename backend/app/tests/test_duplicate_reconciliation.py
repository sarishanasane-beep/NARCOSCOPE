"""CASE-entity / Case reconciliation tests.

A legacy CASE-typed Entity (``Operation WHITE STRIKE [CASE]``) and the
actual Case record represent the same logical Case. These tests verify:

  - type-aware cross-table detection (CASE type only, normalized name),
  - classification: CONFIRMED SAME only when the entity's source document
    is anchored to the Case; POSSIBLE DUPLICATE otherwise,
  - explicit reconciliation marks the entity MERGED + merged_into_case_id
    and preserves every relationship and its provenance,
  - the case graph keeps exactly ONE CASE node with edges routed through
    it (before and after reconciliation),
  - normalized (case/whitespace-insensitive) matching,
  - same-name people are NEVER auto-merged (POSSIBLE DUPLICATE only),
  - POSSIBLE_MATCH candidates remain PENDING candidates,
  - ingestion-time prevention: confirming a CASE-typed relationship
    endpoint reuses/reconciles into the canonical Case instead of
    creating an independent record,
  - the /entities?status= data-quality filter works.
"""

import uuid

from app.models.candidate import Candidate
from app.models.case import Case
from app.models.event import Event
from app.models.entity import (
    ENTITY_STATUS_ACTIVE,
    ENTITY_STATUS_MERGED,
    ENTITY_TYPE_CASE,
    ENTITY_TYPE_PERSON,
    Entity,
)
from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
from app.services.entities.duplicates import (
    detect_duplicates,
    reconcile_case_entity,
)
from app.services.entities.resolution import create_entity
from app.services.graph.model import case_node_id, entity_node_id
from app.services.graph.service import graph_service
from app.services.validation.workflow import confirm_candidate
from app.tests import graph_helpers as h


# ---------------------------------------------------------------------------
# Detection (type-aware, cross-table)
# ---------------------------------------------------------------------------


def test_case_entity_duplicate_detected_type_aware(db):
    case = h.case(db, name="Operation WHITE STRIKE")
    dup = create_entity(
        db, entity_type=ENTITY_TYPE_CASE, canonical_name="Operation WHITE STRIKE", user="tester"
    )
    # Same name but PERSON — never matched against a Case (type-aware).
    create_entity(db, entity_type=ENTITY_TYPE_PERSON, canonical_name="Operation WHITE STRIKE", user="tester")
    db.commit()

    groups = detect_duplicates(db, kind="case_entity")
    assert len(groups) == 1
    g = groups[0]
    assert g["kind"] == "case_entity"
    assert g["classification"] == "POSSIBLE_DUPLICATE"
    assert g["case"]["record_id"] == case.case_id
    assert [r["record_id"] for r in g["records"]] == [dup.entity_id]


def test_case_entity_confirmed_same_when_document_anchored(db):
    case = h.case(db, name="Operation WHITE STRIKE")
    doc = h.document(db)
    doc.case_id = case.case_id
    create_entity(
        db,
        entity_type=ENTITY_TYPE_CASE,
        canonical_name="Operation WHITE STRIKE",
        document_id=doc.document_id,
        user="tester",
    )
    db.commit()
    groups = detect_duplicates(db, kind="case_entity")
    assert len(groups) == 1
    assert groups[0]["classification"] == "CONFIRMED_SAME"


def test_normalized_matching_case_insensitive_and_whitespace(db):
    case = h.case(db, name="Operation WHITE STRIKE")
    create_entity(
        db, entity_type=ENTITY_TYPE_CASE, canonical_name="  operation  white strike ", user="tester"
    )
    db.commit()
    groups = detect_duplicates(db, kind="case_entity")
    assert len(groups) == 1
    assert groups[0]["case"]["record_id"] == case.case_id


# ---------------------------------------------------------------------------
# Reconciliation (relationship + provenance preservation, graph compatibility)
# ---------------------------------------------------------------------------


def test_reconcile_preserves_relationships_provenance_and_graph(db):
    case = h.case(db, name="Operation WHITE STRIKE")
    doc = h.document(db)
    doc.case_id = case.case_id
    ncb = h.org(db, "Narcotics Control Bureau")
    dup = create_entity(
        db,
        entity_type=ENTITY_TYPE_CASE,
        canonical_name="Operation WHITE STRIKE",
        document_id=doc.document_id,
        user="tester",
    )
    ev = h.evidence(db, doc, exact_text="NCB conducted Operation WHITE STRIKE.")
    rel1 = h.relationship(db, ncb, dup, "CONDUCTED_OPERATION", evidence=ev, case_row=case)
    mumbai = h.location(db, "Mumbai")
    rel2 = h.relationship(db, dup, mumbai, "OCCURRED_AT", evidence=ev, case_row=case)
    db.commit()

    # Before reconciliation the graph already shows ONE case node (view
    # remap); after reconciliation it must STILL be one node with all
    # edges routed through it.
    def case_edges():
        payload = graph_service.get_case_graph_full(db, case.case_id)
        case_nodes = [n for n in payload["nodes"] if n["type"] == "CASE"]
        cid = case_node_id(case.case_id)
        rel_edges = [
            (e["source"], e["relationship_type"], e["target"])
            for e in payload["edges"] if e["provenance_kind"] == "relationship"
        ]
        return len(case_nodes), rel_edges, cid

    before_nodes, before_edges, cid = case_edges()
    assert before_nodes == 1
    assert (entity_node_id(ncb.entity_id), "CONDUCTED_OPERATION", cid) in before_edges
    assert (cid, "OCCURRED_AT", entity_node_id(mumbai.entity_id)) in before_edges

    result = reconcile_case_entity(
        db, dup.entity_id, case.case_id, user="reviewer", note="same operation"
    )
    assert result["status"] == "reconciled"
    assert result["already"] is False
    db.commit()

    merged = db.get(Entity, dup.entity_id)
    assert merged.status == ENTITY_STATUS_MERGED
    assert merged.merged_into_case_id == case.case_id
    assert merged.structured_metadata["reconciled_into_case_id"] == case.case_id

    # Relationships untouched: endpoints intact, provenance (evidence,
    # case scope) intact — nothing deleted, nothing duplicated.
    r1 = db.get(Relationship, rel1.relationship_id)
    assert r1.source_entity_id == ncb.entity_id
    assert r1.target_entity_id == dup.entity_id
    assert r1.evidence_id == ev.evidence_id
    assert r1.case_id == case.case_id
    assert r1.status == REL_STATUS_CONFIRMED
    r2 = db.get(Relationship, rel2.relationship_id)
    assert r2.source_entity_id == dup.entity_id
    assert r2.target_entity_id == mumbai.entity_id
    assert r2.evidence_id == ev.evidence_id

    # No longer flagged as a possible duplicate.
    assert detect_duplicates(db, kind="case_entity") == []

    # Graph still ONE case node with edges routed through it.
    after_nodes, after_edges, cid = case_edges()
    assert after_nodes == 1
    assert (entity_node_id(ncb.entity_id), "CONDUCTED_OPERATION", cid) in after_edges
    assert (cid, "OCCURRED_AT", entity_node_id(mumbai.entity_id)) in after_edges
    # The merged entity never appears as its own node.
    assert all(n["entity_id"] != dup.entity_id for n in graph_service.get_case_graph_full(db, case.case_id)["nodes"])


def test_reconcile_is_idempotent_and_validates(db):
    case = h.case(db, name="Operation WHITE STRIKE")
    dup = create_entity(db, entity_type=ENTITY_TYPE_CASE, canonical_name="Operation WHITE STRIKE", user="tester")
    person = h.person(db, "Some Person")
    db.commit()

    reconcile_case_entity(db, dup.entity_id, case.case_id, user="reviewer")
    again = reconcile_case_entity(db, dup.entity_id, case.case_id, user="reviewer")
    assert again["already"] is True

    from app.utils.errors import ValidationError

    try:
        reconcile_case_entity(db, person.entity_id, case.case_id, user="reviewer")
        assert False, "non-CASE entity must not be reconcilable"
    except ValidationError:
        pass


# ---------------------------------------------------------------------------
# Same-name people / candidate semantics — never weakened
# ---------------------------------------------------------------------------


def test_same_name_people_not_auto_merged(db):
    p1 = h.person(db, "Suresh Patil")
    p2 = h.person(db, "Suresh Patil")
    db.commit()

    groups = detect_duplicates(db, kind="entity")
    person_groups = [g for g in groups if g["entity_type"] == "PERSON"]
    assert len(person_groups) == 1
    # Name-only match is POSSIBLE_DUPLICATE for human review — never a
    # deterministic auto-merge in an investigation system.
    assert person_groups[0]["classification"] == "POSSIBLE_DUPLICATE"
    assert db.get(Entity, p1.entity_id).status == ENTITY_STATUS_ACTIVE
    assert db.get(Entity, p2.entity_id).status == ENTITY_STATUS_ACTIVE


def test_possible_match_candidate_remains_candidate(client, db):
    cand = Candidate(
        candidate_id=str(uuid.uuid4()),
        candidate_type="POSSIBLE_MATCH",
        proposed_data={"source_entity_id": "a", "target_entity_id": "b", "score": 0.8},
        reason="possible match for human review",
        status="PENDING",
    )
    db.add(cand)
    db.commit()

    items = client.get("/candidates?limit=500").json()["items"]
    matches = [c for c in items if c["candidate_type"] == "POSSIBLE_MATCH"]
    assert len(matches) == 1
    assert matches[0]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Ingestion-time prevention
# ---------------------------------------------------------------------------


def _relationship_candidate(db, source_name, source_type, target_name, target_type, rtype):
    cand = Candidate(
        candidate_id=str(uuid.uuid4()),
        candidate_type="RELATIONSHIP",
        proposed_data={
            "source_name": source_name,
            "source_type": source_type,
            "target_name": target_name,
            "target_type": target_type,
            "relationship_type": rtype,
            "classification": "DIRECT",
        },
        reason="test relationship",
        status="PENDING",
    )
    db.add(cand)
    db.flush()
    return cand


def test_ingestion_reuses_canonical_case_endpoint(db):
    case = h.case(db, name="Operation WHITE STRIKE")
    ncb = h.org(db, "Narcotics Control Bureau")
    db.commit()

    # Confirming a relationship whose TARGET is the declared CASE resolves
    # the canonical Case first and creates a RECONCILED endpoint — never an
    # independent ACTIVE CASE record.
    cand = _relationship_candidate(
        db, "Narcotics Control Bureau", "ORGANIZATION",
        "Operation WHITE STRIKE", "CASE", "CONDUCTED_OPERATION",
    )
    confirm_candidate(db, cand, reviewed_by="reviewer", reason="reviewed")
    db.commit()

    rel = db.query(Relationship).filter(Relationship.relationship_id.isnot(None)).first()
    assert rel is not None
    assert rel.case_id == case.case_id
    endpoint = db.get(Entity, rel.target_entity_id)
    assert endpoint.entity_type == ENTITY_TYPE_CASE
    assert endpoint.status == ENTITY_STATUS_MERGED
    assert endpoint.merged_into_case_id == case.case_id

    # No independent ACTIVE CASE-typed record was created.
    active_case_entities = [
        e for e in db.query(Entity).filter(Entity.entity_type == ENTITY_TYPE_CASE).all()
        if e.status == ENTITY_STATUS_ACTIVE
    ]
    assert active_case_entities == []

    # A second relationship against the same case reuses the SAME endpoint.
    cand2 = _relationship_candidate(
        db, "Mumbai", "LOCATION",
        "Operation WHITE STRIKE", "CASE", "OCCURRED_AT",
    )
    confirm_candidate(db, cand2, reviewed_by="reviewer", reason="reviewed")
    db.commit()

    case_entities = db.query(Entity).filter(Entity.entity_type == ENTITY_TYPE_CASE).all()
    assert len(case_entities) == 1
    assert case_entities[0].merged_into_case_id == case.case_id

    # Graph: exactly ONE case node; both edges route through it.
    payload = graph_service.get_case_graph_full(db, case.case_id)
    case_nodes = [n for n in payload["nodes"] if n["type"] == "CASE"]
    assert len(case_nodes) == 1
    cid = case_node_id(case.case_id)
    rel_edges = {
        (e["source"], e["relationship_type"], e["target"])
        for e in payload["edges"] if e["provenance_kind"] == "relationship"
    }
    mumbai = db.query(Entity).filter(Entity.canonical_name == "Mumbai", Entity.entity_type == "LOCATION").first()
    assert (entity_node_id(ncb.entity_id), "CONDUCTED_OPERATION", cid) in rel_edges
    # Declared direction: Mumbai OCCURRED_AT the CASE — the CASE endpoint
    # resolved to the canonical case node.
    assert (entity_node_id(mumbai.entity_id), "OCCURRED_AT", cid) in rel_edges


# ---------------------------------------------------------------------------
# Data Management API
# ---------------------------------------------------------------------------


def test_duplicates_api_exposes_case_entity_groups(client, db):
    case = h.case(db, name="Operation WHITE STRIKE")
    create_entity(db, entity_type=ENTITY_TYPE_CASE, canonical_name="Operation WHITE STRIKE", user="tester")
    db.commit()

    data = client.get("/duplicates?kind=case_entity").json()
    groups = data["groups"]
    assert len(groups) == 1
    assert groups[0]["kind"] == "case_entity"
    assert data["summary"]["case_entity_reconciliation_groups"] == 1


def test_case_search_normalized(client, db):
    h.case(db, name="Operation WHITE STRIKE")
    db.commit()
    items = client.get("/cases?q=" + "  operation  white strike ").json()["items"]
    assert [c["case_name"] for c in items] == ["Operation WHITE STRIKE"]
    # Display name preserved — only the comparison is normalized.
    assert items[0]["case_name"] == "Operation WHITE STRIKE"


def test_entities_status_filter(client, db):
    create_entity(db, entity_type=ENTITY_TYPE_PERSON, canonical_name="Active Person", user="tester")
    case = h.case(db, name="Operation WHITE STRIKE")
    dup = create_entity(db, entity_type=ENTITY_TYPE_CASE, canonical_name="Operation WHITE STRIKE", user="tester")
    db.commit()
    reconcile_case_entity(db, dup.entity_id, case.case_id, user="reviewer")
    db.commit()

    active = client.get("/entities?status=ACTIVE").json()
    assert any(e["canonical_name"] == "Active Person" for e in active["items"])
    assert not any(e["canonical_name"] == "Operation WHITE STRIKE" for e in active["items"])

    merged = client.get("/entities?status=MERGED").json()
    assert any(
        e["canonical_name"] == "Operation WHITE STRIKE" and e["merged_into_case_id"] == case.case_id
        for e in merged["items"]
    )


# ---------------------------------------------------------------------------
# One canonical graph node per logical entity (REQ 17-19)
# ---------------------------------------------------------------------------


def test_case_graph_one_canonical_node_per_legacy_duplicate_entity(db):
    """A legacy entity row (created by older document processing) that has
    the same (entity_type, normalized name) as the case's OWN document row
    is the same logical entity. The case graph must emit ONE canonical node
    and route relationship/event-location edges through it — never a
    duplicate-looking node."""
    from app.models.location import Location

    case = h.case(db, name="Operation WHITE STRIKE")
    doc = h.document(db, filename="v2_white_strike.txt")
    doc.case_id = case.case_id
    # The case's own document created the canonical rows.
    canon_ncb = create_entity(
        db, entity_type="ORGANIZATION", canonical_name="Narcotics Control Bureau",
        document_id=doc.document_id, user="tester",
    )
    canon_mumbai = create_entity(
        db, entity_type="LOCATION", canonical_name="Mumbai",
        document_id=doc.document_id, user="tester",
    )
    db.flush()
    # The legacy duplicate rows (older document) share type + normalized
    # name — plain Entity rows, exactly like rows created by older document
    # processing (they may not even have a specialized row).
    legacy_ncb = Entity(
        entity_id=str(uuid.uuid4()), entity_type="ORGANIZATION",
        canonical_name="Narcotics Control Bureau", status=ENTITY_STATUS_ACTIVE,
    )
    legacy_mumbai = Entity(
        entity_id=str(uuid.uuid4()), entity_type="LOCATION",
        canonical_name="Mumbai", status=ENTITY_STATUS_ACTIVE,
    )
    db.add(legacy_ncb)
    db.add(legacy_mumbai)
    db.flush()
    # Relationships reference the LEGACY rows (endpoint resolution before
    # canonical identity existed).
    ev = h.evidence(db, doc, exact_text="NCB conducted Operation WHITE STRIKE in Mumbai.")
    h.relationship(db, legacy_ncb, legacy_mumbai, "OCCURRED_AT", evidence=ev, case_row=case)
    # An event at the legacy Mumbai location.
    loc = Location(
        location_id=str(uuid.uuid4()), entity_id=legacy_mumbai.entity_id,
        canonical_name="Mumbai", location_type="CITY",
    )
    db.add(loc)
    db.flush()
    h.event(db, title="Drug seizure", case_row=case, location_entity=None)
    ev_row = db.query(Event).filter(Event.title == "Drug seizure").first()
    ev_row.location_id = loc.location_id
    db.commit()

    payload = graph_service.get_case_graph_full(db, case.case_id)
    nodes = payload["nodes"]
    edges = payload["edges"]

    # Exactly ONE NCB node and ONE Mumbai node.
    ncb_nodes = [n for n in nodes if n["name"] == "Narcotics Control Bureau"]
    mumbai_nodes = [n for n in nodes if n["name"] == "Mumbai"]
    assert len(ncb_nodes) == 1
    assert len(mumbai_nodes) == 1
    # The canonical node is the case document's row, not the legacy row.
    assert ncb_nodes[0]["entity_id"] == canon_ncb.entity_id
    assert mumbai_nodes[0]["entity_id"] == canon_mumbai.entity_id
    # No node carries the legacy entity ids.
    node_ids = {n["id"] for n in nodes}
    assert entity_node_id(legacy_ncb.entity_id) not in node_ids
    assert entity_node_id(legacy_mumbai.entity_id) not in node_ids
    # Edges route through the canonical nodes (source/target ids present).
    edge_ids = {e["source"] for e in edges} | {e["target"] for e in edges}
    assert entity_node_id(canon_ncb.entity_id) in edge_ids
    assert entity_node_id(canon_mumbai.entity_id) in edge_ids
    # The event -> location edge points at the canonical Mumbai node.
    ev_loc = [e for e in edges if e["provenance_kind"] == "event_location"]
    assert len(ev_loc) == 1
    assert ev_loc[0]["target"] == entity_node_id(canon_mumbai.entity_id)


def test_case_graph_keeps_genuinely_distinct_entities_separate(db):
    """Same display name but DIFFERENT entity types are distinct logical
    entities — never collapsed (REQ 19: ENT-MUMBAI vs ENT-NAVI-MUMBAI)."""
    case = h.case(db, name="Operation WHITE STRIKE")
    doc = h.document(db, filename="v2_white_strike.txt")
    doc.case_id = case.case_id
    city = create_entity(
        db, entity_type="LOCATION", canonical_name="Navi Mumbai",
        document_id=doc.document_id, user="tester",
    )
    # A PERSON with the same name is NOT the same logical entity.
    person = create_entity(
        db, entity_type=ENTITY_TYPE_PERSON, canonical_name="Navi Mumbai", user="tester",
    )
    db.commit()

    payload = graph_service.get_case_graph_full(db, case.case_id)
    names = [n["name"] for n in payload["nodes"] if n["name"] == "Navi Mumbai"]
    # Only the case-document LOCATION row is in the graph (the PERSON row is
    # not part of this case's documents and has no edges).
    assert len(names) == 1
    nodes = payload["nodes"]
    assert any(n["name"] == "Navi Mumbai" and n["type"] == "LOCATION" for n in nodes)
    assert not any(n["name"] == "Navi Mumbai" and n["type"] == "PERSON" for n in nodes)
