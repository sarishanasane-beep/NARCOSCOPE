"""PROMPT 2 PART 1 — TRUSTED MASTER KNOWLEDGE GRAPH TESTS.

Covers:
- graph construction from confirmed records (person/org/location/event/
  case nodes; relationship/fact/event edges with preserved metadata)
- the ABSOLUTE TRUST BOUNDARY: pending/rejected/candidate/POSSIBLE_MATCH
  information never enters the graph
- canonical entity identity (one node per trusted entity across cases)
- date correctness (precision preserved; event date and document
  publication date kept separate)
- provenance (edge -> relationship/fact -> evidence -> document -> source)
- the graph API endpoints
"""

from datetime import date

import uuid

from app.models.candidate import (
    CANDIDATE_STATUS_PENDING,
    CANDIDATE_STATUS_REJECTED,
    CANDIDATE_TYPE_ENTITY,
    CANDIDATE_TYPE_RELATIONSHIP,
    Candidate,
)
from app.models.case import Case
from app.models.document import Document
from app.models.entity import Entity
from app.models.evidence import Evidence
from app.models.event import Event
from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.models.location import Location
from app.models.relationship import (
    CLASSIFICATION_CANDIDATE,
    CLASSIFICATION_DERIVED,
    CLASSIFICATION_DIRECT,
    REL_STATUS_CANDIDATE,
    REL_STATUS_CONFIRMED,
    REL_STATUS_REJECTED,
    Relationship,
)
from app.models.source import Source
from app.services.entities.resolution import create_entity
from app.services.graph.builder import build_trusted_graph
from app.services.graph.model import case_node_id, entity_node_id, event_node_id
from app.tests.conftest import make_txt_bytes, upload_bytes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _person(db, name="Suresh Patil", aliases=None):
    return create_entity(db, entity_type="PERSON", canonical_name=name, aliases=aliases or [])


def _org(db, name="Narcotics Control Bureau"):
    return create_entity(db, entity_type="ORGANIZATION", canonical_name=name)


def _location(db, name="Mumbai"):
    return create_entity(db, entity_type="LOCATION", canonical_name=name)


def _operation(db, name="Operation Bluewater"):
    return create_entity(db, entity_type="OTHER", canonical_name=name)


def _case(db, number=None, name=None):
    case = Case(
        case_id=str(uuid.uuid4()),
        official_case_number=number,
        case_name=name,
        status="UNKNOWN",
    )
    db.add(case)
    db.flush()
    return case


def _event(db, title="Operation Bluewater", event_type="OPERATION", precision="DAY",
           start=None, case=None, location_entity=None):
    event = Event(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        title=title,
        date_precision=precision,
        start_date=date.fromisoformat(start) if start else None,
        case_id=case.case_id if case else None,
        location_id=location_entity.location.location_id if location_entity else None,
    )
    db.add(event)
    db.flush()
    return event


def _document(db, filename="report.txt", publication_date=None):
    doc = Document(
        document_id=str(uuid.uuid4()),
        filename=filename,
        stored_filename=filename,
        file_type="txt",
        mime_type="text/plain",
        file_size=10,
        sha256_hash="0" * 64,
        storage_path="/tmp/x.txt",
        processing_status="PROCESSED",
        publication_date=publication_date,
    )
    db.add(doc)
    db.flush()
    return doc


def _source(db, publisher="Demo Press", agency="Demo Agency", source_type="SECONDARY_SOURCE",
            publication_date=None):
    src = Source(
        source_id=str(uuid.uuid4()),
        publisher=publisher,
        agency=agency,
        source_type=source_type,
        publication_date=publication_date,
    )
    db.add(src)
    db.flush()
    return src


def _evidence(db, document, source=None, exact_text="Arjun Mehta was arrested during Operation Bluewater."):
    ev = Evidence(
        evidence_id=str(uuid.uuid4()),
        document_id=document.document_id,
        source_id=source.source_id if source else None,
        exact_text=exact_text,
        extraction_method="deterministic_rules",
        extraction_confidence=0.9,
    )
    db.add(ev)
    db.flush()
    return ev


def _relationship(db, source, target, rtype, classification=CLASSIFICATION_DIRECT,
                  status=REL_STATUS_CONFIRMED, confidence=0.9, evidence=None, case=None, event=None):
    rel = Relationship(
        relationship_id=str(uuid.uuid4()),
        source_entity_id=source.entity_id,
        relationship_type=rtype,
        target_entity_id=target.entity_id,
        classification=classification,
        status=status,
        confidence=confidence,
        evidence_id=evidence.evidence_id if evidence else None,
        case_id=case.case_id if case else None,
        event_id=event.event_id if event else None,
    )
    db.add(rel)
    db.flush()
    return rel


def _fact(db, subject, predicate, case=None, event=None, object_entity=None, evidence=None):
    fact = Fact(
        fact_id=str(uuid.uuid4()),
        subject_entity_id=subject.entity_id,
        predicate=predicate,
        object_entity_id=object_entity.entity_id if object_entity else None,
        case_id=case.case_id if case else None,
        event_id=event.event_id if event else None,
        evidence_id=evidence.evidence_id if evidence else None,
        status=FACT_STATUS_CONFIRMED,
        confidence=0.9,
    )
    db.add(fact)
    db.flush()
    return fact


def _candidate(db, name, candidate_type=CANDIDATE_TYPE_ENTITY, status=CANDIDATE_STATUS_PENDING):
    proposed = {"name": name, "entity_type": "PERSON", "aliases": []}
    if candidate_type == CANDIDATE_TYPE_RELATIONSHIP:
        proposed = {
            "source_name": "Suresh Patil",
            "relationship_type": "POSSIBLE_MATCH",
            "target_name": "S. Patil",
            "classification": "CANDIDATE",
        }
    cand = Candidate(
        candidate_id=str(uuid.uuid4()),
        candidate_type=candidate_type,
        proposed_data=proposed,
        reason="test candidate",
        status=status,
    )
    db.add(cand)
    db.flush()
    return cand


def _node_names(db):
    nodes, _ = build_trusted_graph(db)
    return {n.name for n in nodes.values()}


def _edges(db):
    _, edges = build_trusted_graph(db)
    return edges


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def test_confirmed_person_and_organization_in_graph(db):
    person = _person(db)
    org = _org(db)
    db.commit()
    nodes, _ = build_trusted_graph(db)
    assert entity_node_id(person.entity_id) in nodes
    assert entity_node_id(org.entity_id) in nodes
    assert nodes[entity_node_id(person.entity_id)].type == "PERSON"
    assert nodes[entity_node_id(org.entity_id)].type == "ORGANIZATION"


def test_confirmed_relationship_becomes_edge_with_metadata(db):
    person = _person(db)
    operation = _operation(db)
    doc = _document(db)
    source = _source(db)
    evidence = _evidence(db, doc, source)
    rel = _relationship(db, person, operation, "PARTICIPATED_IN", confidence=0.9, evidence=evidence)
    db.commit()
    nodes, edges = build_trusted_graph(db)
    assert entity_node_id(person.entity_id) in nodes
    assert entity_node_id(operation.entity_id) in nodes
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source == entity_node_id(person.entity_id)
    assert edge.target == entity_node_id(operation.entity_id)
    assert edge.relationship_type == "PARTICIPATED_IN"
    assert edge.classification == "DIRECT"
    assert edge.confidence == 0.9
    assert edge.evidence_id == evidence.evidence_id
    assert edge.relationship_id == rel.relationship_id
    assert edge.created_at is not None


def test_confirmed_event_case_location_nodes_and_associations(db):
    case = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    location = _location(db, name="Mumbai")
    event = _event(db, precision="DAY", start="2026-06-15", case=case, location_entity=location)
    db.commit()
    nodes, edges = build_trusted_graph(db)
    assert event_node_id(event.event_id) in nodes
    assert case_node_id(case.case_id) in nodes
    assert entity_node_id(location.entity_id) in nodes
    pairs = {(e.source, e.target, e.relationship_type) for e in edges}
    assert (event_node_id(event.event_id), case_node_id(case.case_id), "PART_OF") in pairs
    assert (event_node_id(event.event_id), entity_node_id(location.entity_id), "OCCURRED_IN") in pairs


def test_confirmed_fact_subject_to_case_edge(db):
    person = _person(db)
    case = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    _fact(db, person, "QUESTIONED_IN", case=case)
    db.commit()
    edges = _edges(db)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source == entity_node_id(person.entity_id)
    assert edge.target == case_node_id(case.case_id)
    assert edge.relationship_type == "QUESTIONED_IN"
    assert edge.classification == "DIRECT"
    assert edge.provenance_kind == "fact"
    assert edge.fact_id is not None


def test_location_hierarchy_edge(db):
    _location(db, name="Maharashtra")
    pune = _location(db, name="Pune")
    # Wire the hierarchy directly (same as the seed's _set_location_parents).
    parent = db.query(Location).join(Entity, Entity.entity_id == Location.entity_id).filter(
        Entity.canonical_name == "Maharashtra"
    ).first()
    pune.location.parent_location_id = parent.location_id
    db.commit()
    edges = _edges(db)
    pairs = {(e.source, e.target, e.relationship_type) for e in edges}
    assert (entity_node_id(pune.entity_id), entity_node_id(parent.entity_id), "LOCATED_IN") in pairs


# ---------------------------------------------------------------------------
# Absolute trust boundary
# ---------------------------------------------------------------------------


def test_pending_candidate_not_in_graph(db):
    _candidate(db, "S. Patil", status=CANDIDATE_STATUS_PENDING)
    db.commit()
    assert "S. Patil" not in _node_names(db)


def test_rejected_candidate_not_in_graph(db):
    _candidate(db, "Noise Person", status=CANDIDATE_STATUS_REJECTED)
    db.commit()
    assert "Noise Person" not in _node_names(db)


def test_unconfirmed_and_rejected_relationships_not_in_graph(db):
    person = _person(db)
    operation = _operation(db)
    _relationship(db, person, operation, "PARTICIPATED_IN", status=REL_STATUS_CANDIDATE)
    _relationship(db, person, operation, "INVOLVED_IN", status=REL_STATUS_REJECTED)
    db.commit()
    assert _edges(db) == []


def test_possible_match_never_enters_trusted_graph(db):
    suresh = _person(db, name="Suresh Patil")
    s_patil = create_entity(db, entity_type="PERSON", canonical_name="S. Patil")
    # Candidate-level POSSIBLE_MATCH (the normal case).
    _candidate(db, "S. Patil", candidate_type=CANDIDATE_TYPE_RELATIONSHIP, status=CANDIDATE_STATUS_PENDING)
    # Belt-and-braces: even a CONFIRMED-status POSSIBLE_MATCH row must be
    # excluded from the trusted graph.
    _relationship(
        db, suresh, s_patil, "POSSIBLE_MATCH",
        status=REL_STATUS_CONFIRMED, classification=CLASSIFICATION_CANDIDATE,
    )
    db.commit()
    edges = _edges(db)
    assert edges == []
    assert not any(e.relationship_type == "POSSIBLE_MATCH" for e in edges)


def test_candidate_classification_relationship_excluded(db):
    person = _person(db)
    operation = _operation(db)
    _relationship(
        db, person, operation, "PARTICIPATED_IN",
        classification=CLASSIFICATION_CANDIDATE, status=REL_STATUS_CONFIRMED,
    )
    db.commit()
    assert _edges(db) == []


# ---------------------------------------------------------------------------
# Canonical entity identity
# ---------------------------------------------------------------------------


def test_same_person_across_two_cases_is_one_node(db):
    person = _person(db)
    case_a = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    case_b = _case(db, number="NCB/MUM/456/2026", name="CASE-002")
    _fact(db, person, "QUESTIONED_IN", case=case_a)
    _fact(db, person, "QUESTIONED_IN", case=case_b)
    db.commit()
    nodes, edges = build_trusted_graph(db)
    person_nodes = [n for n in nodes.values() if n.type == "PERSON" and n.name == "Suresh Patil"]
    assert len(person_nodes) == 1, "one canonical node for one trusted person"
    pairs = {(e.source, e.target, e.relationship_type) for e in edges}
    assert (entity_node_id(person.entity_id), case_node_id(case_a.case_id), "QUESTIONED_IN") in pairs
    assert (entity_node_id(person.entity_id), case_node_id(case_b.case_id), "QUESTIONED_IN") in pairs


def test_same_organization_across_cases_is_one_node(db):
    org = _org(db)
    case_a = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    case_b = _case(db, number="NCB/MUM/456/2026", name="CASE-002")
    _fact(db, org, "INVOLVED_IN", case=case_a)
    _fact(db, org, "INVOLVED_IN", case=case_b)
    db.commit()
    nodes, edges = build_trusted_graph(db)
    org_nodes = [n for n in nodes.values() if n.type == "ORGANIZATION" and n.name == "Narcotics Control Bureau"]
    assert len(org_nodes) == 1, "one canonical node for one trusted organization"
    pairs = {(e.source, e.target) for e in edges}
    assert (entity_node_id(org.entity_id), case_node_id(case_a.case_id)) in pairs
    assert (entity_node_id(org.entity_id), case_node_id(case_b.case_id)) in pairs


# ---------------------------------------------------------------------------
# Date correctness
# ---------------------------------------------------------------------------


def test_event_date_precision_preserved(db):
    day_ev = _event(db, title="Operation Bluewater", precision="DAY", start="2026-06-15")
    month_ev = _event(db, title="Seizure in June", precision="MONTH", start="2026-06-01")
    year_ev = _event(db, title="Records 2025", precision="YEAR", start="2025-01-01")
    unknown_ev = _event(db, title="Unknown date event", precision="UNKNOWN", start=None)
    db.commit()
    nodes, _ = build_trusted_graph(db)
    by_id = {n.id: n for n in nodes.values()}
    day = by_id[event_node_id(day_ev.event_id)]
    assert day.start_date == "2026-06-15" and day.date_precision == "DAY"
    month = by_id[event_node_id(month_ev.event_id)]
    assert month.start_date == "2026-06-01" and month.date_precision == "MONTH"
    year = by_id[event_node_id(year_ev.event_id)]
    assert year.start_date == "2025-01-01" and year.date_precision == "YEAR"
    unknown = by_id[event_node_id(unknown_ev.event_id)]
    assert unknown.start_date is None and unknown.date_precision == "UNKNOWN"


def test_unknown_date_stays_unknown(db):
    event = _event(db, title="Interception", precision="UNKNOWN", start=None)
    db.commit()
    nodes, _ = build_trusted_graph(db)
    node = nodes[event_node_id(event.event_id)]
    assert node.start_date is None
    assert node.date_precision == "UNKNOWN"


def test_event_date_and_publication_date_kept_separate(client, db):
    person = _person(db)
    operation = _operation(db)
    case = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    event = _event(db, precision="DAY", start="2026-06-15", case=case)
    doc = _document(db, filename="report.txt", publication_date=date(2026, 7, 1))
    source = _source(db, publisher="Demo Press", publication_date=date(2026, 7, 1))
    evidence = _evidence(db, doc, source)
    rel = _relationship(db, person, operation, "PARTICIPATED_IN", evidence=evidence,
                        case=case, event=event)
    db.commit()
    payload = client.get(f"/graph/provenance/relationship/{rel.relationship_id}").json()
    # Event date (DAY precision, 2026-06-15) is separate from the document
    # publication date (2026-07-01) — never mixed.
    assert payload["event"]["date_precision"] == "DAY"
    assert payload["event"]["title"] == "Operation Bluewater"
    assert payload["document"]["publication_date"] == "2026-07-01"
    assert payload["document"]["filename"] == "report.txt"
    assert payload["source"]["publisher"] == "Demo Press"
    assert payload["source"]["publication_date"] == "2026-07-01"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_relationship_to_evidence_document_source(client, db):
    person = _person(db, name="Arjun Mehta")
    operation = _operation(db)
    doc = _document(db, filename="raid.txt", publication_date=date(2026, 6, 20))
    source = _source(db, publisher="Demo Press", agency="Demo Agency",
                     source_type="SECONDARY_SOURCE", publication_date=date(2026, 6, 20))
    evidence = _evidence(db, doc, source,
                         exact_text="Arjun Mehta was arrested during Operation Bluewater.")
    rel = _relationship(db, person, operation, "ARRESTED_IN", evidence=evidence)
    db.commit()
    payload = client.get(f"/graph/provenance/relationship/{rel.relationship_id}").json()
    assert payload["relationship_type"] == "ARRESTED_IN"
    assert payload["classification"] == "DIRECT"
    assert payload["evidence"]["exact_text"] == "Arjun Mehta was arrested during Operation Bluewater."
    assert payload["document"]["filename"] == "raid.txt"
    assert payload["source"]["publisher"] == "Demo Press"
    assert payload["source"]["source_type"] == "SECONDARY_SOURCE"


def test_provenance_fact_to_evidence(client, db):
    person = _person(db, name="Vikram Jadhav")
    case = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    doc = _document(db, filename="court.txt", publication_date=date(2026, 7, 6))
    source = _source(db, publisher="Court", source_type="COURT_PUBLIC_RECORD")
    evidence = _evidence(
        db, doc, source,
        exact_text="Vikram Jadhav was questioned in connection with Case CASE-001.",
    )
    fact = _fact(db, person, "QUESTIONED_IN", case=case, evidence=evidence)
    db.commit()
    payload = client.get(f"/graph/provenance/fact/{fact.fact_id}").json()
    assert payload["relationship_type"] == "QUESTIONED_IN"
    assert payload["evidence"]["exact_text"] == evidence.exact_text
    assert payload["document"]["filename"] == "court.txt"
    assert payload["source"]["publisher"] == "Court"


# ---------------------------------------------------------------------------
# Graph API
# ---------------------------------------------------------------------------


def test_entity_graph_endpoint(client, db):
    person = _person(db, name="Arjun Mehta")
    operation = _operation(db)
    _relationship(db, person, operation, "ARRESTED_IN")
    db.commit()
    resp = client.get(f"/graph/entity/{person.entity_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["center"]["id"] == entity_node_id(person.entity_id)
    names = {n["name"] for n in payload["nodes"]}
    assert "Arjun Mehta" in names
    assert "Operation Bluewater" in names
    assert any(e["relationship_type"] == "ARRESTED_IN" for e in payload["edges"])


def test_case_event_location_graph_endpoints(client, db):
    case = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    location = _location(db, name="Mumbai")
    event = _event(db, precision="DAY", start="2026-06-15", case=case, location_entity=location)
    db.commit()
    case_resp = client.get(f"/graph/case/{case.case_id}")
    assert case_resp.status_code == 200
    assert case_resp.json()["center"]["id"] == case_node_id(case.case_id)
    event_resp = client.get(f"/graph/event/{event.event_id}")
    assert event_resp.status_code == 200
    loc_resp = client.get(f"/graph/location/{location.location.location_id}")
    assert loc_resp.status_code == 200
    assert loc_resp.json()["center"]["id"] == entity_node_id(location.entity_id)
    edge_types = {(e["source"], e["target"], e["relationship_type"]) for e in event_resp.json()["edges"]}
    assert (event_node_id(event.event_id), case_node_id(case.case_id), "PART_OF") in edge_types
    assert (event_node_id(event.event_id), entity_node_id(location.entity_id), "OCCURRED_IN") in edge_types


def test_graph_stats_endpoint(client, db):
    person = _person(db)
    operation = _operation(db)
    _relationship(db, person, operation, "ARRESTED_IN")
    db.commit()
    stats = client.get("/graph/stats").json()
    assert stats["total_nodes"] >= 2
    assert stats["total_edges"] >= 1
    assert stats["nodes_by_type"].get("PERSON", 0) >= 1
    assert stats["edges_by_type"].get("ARRESTED_IN", 0) >= 1


def test_graph_endpoint_missing_entity_404(client, db):
    resp = client.get(f"/graph/entity/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_search_result_contract_for_views(client, db):
    """Search results carry the ids/kinds the investigation views need."""
    person = _person(db, name="Arjun Mehta")
    case = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    event = _event(db, title="Operation Bluewater", precision="DAY", start="2026-06-15", case=case)
    db.commit()
    search = client.get("/search?q=Arjun").json()
    assert any(e["entity_id"] == person.entity_id and e["entity_type"] == "PERSON"
               for e in search["entities"])
    cases = client.get("/search?q=CASE-001").json()
    assert any(c["case_id"] == case.case_id for c in cases["cases"])
    events = client.get("/search?q=Operation").json()
    assert any(e["event_id"] == event.event_id for e in events["events"])


def test_end_to_end_upload_confirm_graph(client):
    """Real pipeline: upload -> confirm -> trusted graph contains only
    confirmed records."""
    text = (
        "DEMO DATA test. Arjun Mehta was arrested during Operation Bluewater in "
        "Mumbai on 15 June 2026. The case number is NCB/MUM/123/2026."
    )
    upload_bytes(client, "graph_e2e.txt", make_txt_bytes(text))
    items = client.get("/candidates").json()["items"]
    pending = [c for c in items if c["status"] == "PENDING"]
    assert pending

    def confirm(c):
        resp = client.post(
            f"/candidates/{c['candidate_id']}/confirm",
            json={"reviewed_by": "graph-test", "reason": "graph e2e"},
        )
        assert resp.status_code == 200

    person_candidate = next(
        c for c in pending
        if c["candidate_type"] in ("ENTITY", "LOCATION")
        and c["proposed_data"].get("name") == "Arjun Mehta"
    )
    rel_candidate = next(
        c for c in pending
        if c["candidate_type"] == "RELATIONSHIP"
        and c["proposed_data"].get("source_name") == "Arjun Mehta"
    )
    confirm(person_candidate)
    confirm(rel_candidate)

    entities = client.get("/entities?entity_type=PERSON").json()["items"]
    arjun = next(e for e in entities if e["canonical_name"] == "Arjun Mehta")
    payload = client.get(f"/graph/entity/{arjun['entity_id']}").json()
    names = {n["name"] for n in payload["nodes"]}
    assert names == {"Arjun Mehta", "Operation Bluewater"}
    assert any(e["relationship_type"] == "ARRESTED_IN" for e in payload["edges"])
    assert all(e["relationship_type"] != "POSSIBLE_MATCH" for e in payload["edges"])
    # The still-pending event candidate never becomes an event node.
    assert all(n["node_kind"] != "event" for n in payload["nodes"])

    stats = client.get("/graph/stats").json()
    assert stats["total_nodes"] == 2
    assert stats["total_edges"] == 1
