"""CASE-SCOPED FULL GRAPH + STRUCTURED SCHEMA TESTS.

Verifies the case-centric graph architecture:

- one structured TXT document = one case graph (full trusted graph by
  default, no automatic filters),
- the CASE is the logical root/center without fabricated edges,
- isolated / mentioned-only entities stay visible via their source
  document (never connected by invented edges),
- case A never shows case B data,
- structured schema additions: CASE STATUS/DESCRIPTION, entity
  DESCRIPTION/EVIDENCE, DRUG TYPE/STATUS/VALUE, EVENT TIME /
  DATE_PRECISION / DRUG / VEHICLE, RELATIONSHIP SOURCE_TYPE /
  TARGET_TYPE / CLASSIFICATION with conflict surfacing,
- event source-document/evidence linkage is direct (document_id,
  evidence_id on the trusted Event).

No database reset is performed: the per-test fixture truncates the
isolated test database only.
"""

from app.tests.conftest import upload_bytes


def _candidates(client):
    return client.get("/candidates").json()["items"]


def _proposed(candidate):
    return candidate["proposed_data"]


def _entity_candidates(client):
    return [
        c for c in _candidates(client)
        if c["candidate_type"] in ("ENTITY", "LOCATION")
    ]


def _confirm_all(client, candidate_type: str | None = None):
    for c in _candidates(client):
        if candidate_type and c["candidate_type"] != candidate_type:
            continue
        resp = client.post(f"/candidates/{c['candidate_id']}/confirm", json={"reason": "reviewed"})
        assert resp.status_code == 200, resp.text


CASE_A_DOC = """\
DOCUMENT:
TITLE: Operation WHITE STRIKE
DATE: 01 May 2026
SOURCE: Narcotics Control Bureau

CASE:
NAME: Operation WHITE STRIKE
TYPE: DRUG_TRAFFICKING_INVESTIGATION
STATUS: ACTIVE_INVESTIGATION
DESCRIPTION: NCB operation against a transnational cocaine syndicate.

PERSON:
NAME: Person A
ROLE: ACCUSED
STATUS: ARRESTED

PERSON:
NAME: Amit Shah
ROLE: UNION HOME MINISTER
STATUS: GOVERNMENT_OFFICIAL
MENTION_CONTEXT: CONTEXTUAL

ORGANIZATION:
NAME: Narcotics Control Bureau
ROLE: INVESTIGATING_AGENCY

LOCATION:
NAME: Mumbai
TYPE: CITY

DRUG:
NAME: Cocaine
QUANTITY: 349 kg
VALUE: INR 1,745 crore
STATUS: SEIZED
DESCRIPTION: High-grade cocaine.

EVENT:
TYPE: DRUG_SEIZURE
DATE: 01 May 2026
TIME: 14:30
DATE_PRECISION: DAY
LOCATION: Mumbai region
DESCRIPTION: NCB seized 349 kg of cocaine.
STATUS: CONFIRMED_OPERATION
DURATION: 2 hours
DRUG: Cocaine

RELATIONSHIP:
SOURCE: Narcotics Control Bureau
SOURCE_TYPE: ORGANIZATION
RELATIONSHIP_TYPE: CONDUCTED_OPERATION
TARGET: Operation WHITE STRIKE
TARGET_TYPE: CASE
CLASSIFICATION: DIRECT

RELATIONSHIP:
SOURCE: Operation WHITE STRIKE
RELATIONSHIP_TYPE: INVOLVED_DRUG
TARGET: Cocaine
"""


# ---------------------------------------------------------------------------
# One document = one case graph (REQ 1, 3, 27)
# ---------------------------------------------------------------------------


def test_one_case_creates_one_case_graph(client):
    """REQ 1/3 — one structured document produces one case with a full
    trusted graph available at /graph/case/{id}/full (no filters active)."""
    upload_bytes(client, "case_a.txt", CASE_A_DOC.encode("utf-8"))
    _confirm_all(client)

    cases = client.get("/cases").json()["items"]
    assert len(cases) == 1
    case = cases[0]
    assert case["case_name"] == "Operation WHITE STRIKE"
    # CASE STATUS/DESCRIPTION from the structured block are preserved.
    assert case["status"] == "ACTIVE_INVESTIGATION"
    assert "cocaine syndicate" in (case["description"] or "")

    payload = client.get(f"/graph/case/{case['case_id']}/full").json()
    assert payload["center"]["node_kind"] == "case"
    assert payload["center"]["name"] == "Operation WHITE STRIKE"
    node_names = {n["name"] for n in payload["nodes"]}
    # Full graph by default: case, entity, event, locations, isolated people.
    assert "Operation WHITE STRIKE" in node_names
    assert "Narcotics Control Bureau" in node_names
    assert "Cocaine" in node_names
    assert "Person A" in node_names
    assert "Amit Shah" in node_names  # isolated — never connected
    assert "Mumbai" in node_names
    assert payload["events_total"] == 1
    assert payload["relationships_total"] == 2


def test_case_graph_isolated_entity_has_no_edges(client):
    """REQ 4/22 — a mentioned-only person stays an isolated node in the case
    graph: present as a node, zero incident edges, no fabricated link."""
    upload_bytes(client, "case_a.txt", CASE_A_DOC.encode("utf-8"))
    _confirm_all(client)

    case = client.get("/cases").json()["items"][0]
    payload = client.get(f"/graph/case/{case['case_id']}/full").json()
    amit = next(n for n in payload["nodes"] if n["name"] == "Amit Shah")
    edge_node_ids = {e["source"] for e in payload["edges"]} | {e["target"] for e in payload["edges"]}
    assert amit["id"] not in edge_node_ids
    assert amit["investigative_status"] == "CONTEXTUAL"


def test_case_graph_scoped_excludes_other_case(client):
    """REQ 27 — case A's graph never shows case B's entities/relationships."""
    case_b_doc = (
        "DOCUMENT:\nTITLE: Operation NIGHT FALL\n\n"
        "CASE:\nNAME: Operation NIGHT FALL\nTYPE: ARMS_TRAFFICKING_INVESTIGATION\n\n"
        "PERSON:\nNAME: Ravi Kumar\nROLE: ACCUSED\n\n"
        "DRUG:\nNAME: MDMA\n\n"
        "RELATIONSHIP:\nSOURCE: Ravi Kumar\nRELATIONSHIP_TYPE: INVOLVED_IN\nTARGET: Operation NIGHT FALL\n"
    )
    upload_bytes(client, "case_a.txt", CASE_A_DOC.encode("utf-8"))
    upload_bytes(client, "case_b.txt", case_b_doc.encode("utf-8"))
    _confirm_all(client)

    cases = {c["case_name"]: c for c in client.get("/cases").json()["items"]}
    payload_a = client.get(f"/graph/case/{cases['Operation WHITE STRIKE']['case_id']}/full").json()
    names_a = {n["name"] for n in payload_a["nodes"]}
    assert "Ravi Kumar" not in names_a
    assert "MDMA" not in names_a
    assert "Operation NIGHT FALL" not in names_a
    rel_types_a = {e["relationship_type"] for e in payload_a["edges"]}
    assert "INVOLVED_IN" not in rel_types_a

    payload_b = client.get(f"/graph/case/{cases['Operation NIGHT FALL']['case_id']}/full").json()
    names_b = {n["name"] for n in payload_b["nodes"]}
    assert "Ravi Kumar" in names_b
    assert "MDMA" in names_b
    assert "Amit Shah" not in names_b


def test_case_graph_404_unknown_case(client):
    payload = client.get("/graph/case/does-not-exist/full")
    assert payload.status_code == 404


def test_case_graph_no_duplicate_case_entity(client):
    """REQ 8/M — a CASE-typed ENTITY endpoint with the case name is the same
    logical object as the Case. The case graph must show ONE case node and
    remap relationship endpoints to it: never a duplicate CASE node."""
    upload_bytes(client, "case_a.txt", CASE_A_DOC.encode("utf-8"))
    _confirm_all(client)

    case = client.get("/cases").json()["items"][0]
    payload = client.get(f"/graph/case/{case['case_id']}/full").json()

    # Exactly one WHITE STRIKE node: the case node, which is the center.
    ws_nodes = [n for n in payload["nodes"] if "WHITE STRIKE" in n["name"].upper()]
    assert len(ws_nodes) == 1
    assert ws_nodes[0]["node_kind"] == "case"
    assert ws_nodes[0]["id"] == payload["center"]["id"]
    # No entity node may carry type CASE (the duplicate endpoint form).
    assert not any(n["node_kind"] == "entity" and n["type"] == "CASE" for n in payload["nodes"])
    # Edges referencing the case are remapped to the single case node.
    conducted = next(e for e in payload["edges"] if e["relationship_type"] == "CONDUCTED_OPERATION")
    assert conducted["target"] == payload["center"]["id"]
    involved = next(e for e in payload["edges"] if e["relationship_type"] == "INVOLVED_DRUG")
    assert involved["source"] == payload["center"]["id"]
    # The duplicate is not counted as an entity.
    assert payload["entities_total"] == 5  # NCB, Mumbai, Cocaine, Person A, Amit Shah


# ---------------------------------------------------------------------------
# Event time / precision / document linkage (REQ 10, 11, 28)
# ---------------------------------------------------------------------------


def test_event_time_and_precision_preserved(client):
    """REQ 10/11 — an explicit TIME and DATE_PRECISION survive confirmation
    and are exposed by the events API; no date/time is invented."""
    upload_bytes(client, "case_a.txt", CASE_A_DOC.encode("utf-8"))
    event_candidate = next(
        c for c in _candidates(client)
        if c["candidate_type"] == "EVENT"
        and _proposed(c).get("event_type") == "DRUG_SEIZURE"
    )
    proposed = _proposed(event_candidate)
    assert proposed.get("time") == "14:30"
    assert proposed.get("date_precision") == "DAY"
    assert proposed.get("duration") == "2 hours"
    assert proposed.get("drug") == "Cocaine"

    resp = client.post(
        f"/candidates/{event_candidate['candidate_id']}/confirm", json={"reason": "reviewed"}
    )
    assert resp.status_code == 200, resp.text

    events = client.get("/events?event_type=DRUG_SEIZURE").json()["items"]
    assert len(events) == 1
    event = events[0]
    assert event["start_date"] == "2026-05-01"
    assert event["event_time"] == "14:30"
    assert event["date_precision"] == "DAY"
    # Direct source-document linkage (no title-match heuristic needed).
    assert event["document_id"] is not None
    assert event["evidence_id"] is not None
    sm = event["structured_metadata"] or {}
    assert sm.get("duration") == "2 hours"
    assert sm.get("drug") == "Cocaine"
    assert sm.get("status") == "CONFIRMED_OPERATION"


def test_event_time_missing_stays_missing(client):
    """REQ 10 — an event without TIME stays \"not provided\"; the document
    publication date is never used as the event date."""
    doc = (
        "DOCUMENT:\nTITLE: Undated report\nDATE: 01 May 2026\n\n"
        "EVENT:\nTYPE: INTERCEPTION\nLOCATION: Navi Mumbai\n"
        "DESCRIPTION: An interception with no reported date or time.\n"
    )
    upload_bytes(client, "undated.txt", doc.encode("utf-8"))
    event_candidate = next(
        c for c in _candidates(client)
        if c["candidate_type"] == "EVENT" and _proposed(c).get("event_type") == "INTERCEPTION"
    )
    assert _proposed(event_candidate).get("start_date") is None
    assert _proposed(event_candidate).get("time") is None
    client.post(f"/candidates/{event_candidate['candidate_id']}/confirm", json={"reason": "reviewed"})
    event = client.get("/events?event_type=INTERCEPTION").json()["items"][0]
    assert event["start_date"] is None
    assert event["event_time"] is None
    assert event["date_precision"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Relationship explicit types + conflict surfacing (REQ 24)
# ---------------------------------------------------------------------------


def test_relationship_explicit_types_and_classification(client):
    """REQ 24 — SOURCE_TYPE / TARGET_TYPE / CLASSIFICATION are preserved on
    the relationship candidate and confirmed relationship."""
    upload_bytes(client, "case_a.txt", CASE_A_DOC.encode("utf-8"))
    rel = next(
        c for c in _candidates(client)
        if c["candidate_type"] == "RELATIONSHIP"
        and _proposed(c).get("relationship_type") == "CONDUCTED_OPERATION"
    )
    proposed = _proposed(rel)
    assert proposed["source_type"] == "ORGANIZATION"
    assert proposed["target_type"] == "CASE"
    assert proposed["classification"] == "DIRECT"

    resp = client.post(f"/candidates/{rel['candidate_id']}/confirm", json={"reason": "reviewed"})
    assert resp.status_code == 200, resp.text
    trusted = client.get("/relationships").json()["items"]
    assert any(
        r["relationship_type"] == "CONDUCTED_OPERATION"
        and r["classification"] == "DIRECT"
        for r in trusted
    )


def test_relationship_type_conflict_surfaced(client):
    """REQ 24 — an explicit SOURCE_TYPE contradicting a declared entity's
    type is preserved and surfaced for review, never silently resolved."""
    doc = (
        "DRUG:\nNAME: Cocaine\n\n"
        "PERSON:\nNAME: John Doe\n\n"
        "RELATIONSHIP:\nSOURCE: Cocaine\nSOURCE_TYPE: PERSON\n"
        "RELATIONSHIP_TYPE: SEIZED_AT\nTARGET: John Doe\nTARGET_TYPE: PERSON\n"
    )
    upload_bytes(client, "conflict.txt", doc.encode("utf-8"))
    rel = next(c for c in _candidates(client) if c["candidate_type"] == "RELATIONSHIP")
    proposed = _proposed(rel)
    # The explicit declaration wins (PERSON) and the conflict is recorded.
    assert proposed["source_type"] == "PERSON"
    assert proposed.get("type_conflicts") == ["Cocaine: declared DRUG, explicit PERSON"]


# ---------------------------------------------------------------------------
# Entity schema fields (REQ 23, 30)
# ---------------------------------------------------------------------------


def test_drug_entity_extended_fields(client):
    """DRUG TYPE/QUANTITY/VALUE/STATUS/DESCRIPTION/EVIDENCE flow through."""
    upload_bytes(client, "case_a.txt", CASE_A_DOC.encode("utf-8"))
    cocaine = next(
        c for c in _entity_candidates(client)
        if _proposed(c).get("name") == "Cocaine"
    )
    proposed = _proposed(cocaine)
    assert proposed["entity_type"] == "DRUG"
    assert proposed.get("quantity") == "349 kg"
    assert proposed.get("value") == "INR 1,745 crore"
    assert proposed.get("status") == "SEIZED"
    assert proposed.get("description") == "High-grade cocaine."


def test_entity_document_id_set_at_confirmation(client):
    """Entities record their source document at confirmation — this is what
    lets isolated entities appear in the case graph."""
    upload_bytes(client, "case_a.txt", CASE_A_DOC.encode("utf-8"))
    amit = next(
        c for c in _entity_candidates(client)
        if _proposed(c).get("name") == "Amit Shah"
    )
    resp = client.post(f"/candidates/{amit['candidate_id']}/confirm", json={"reason": "reviewed"})
    assert resp.status_code == 200, resp.text
    entities = client.get("/entities").json()["items"]
    amit_entity = next(e for e in entities if e["canonical_name"] == "Amit Shah")
    assert amit_entity["document_id"] is not None
    # Graph node carries the same linkage.
    graph = client.get(f"/graph/entity/{amit_entity['entity_id']}").json()
    assert graph["center"]["document_id"] == amit_entity["document_id"]
