"""PROMPT 2/3 — END-TO-END TRUSTED INVESTIGATION WORKFLOW.

Exercises the complete chain through the real API:

    document -> processing -> evidence -> candidates -> validation ->
    confirmed trusted entities/relationships -> graph -> analytics ->
    provenance -> search -> timeline -> cross-case -> priority ->
    snapshot -> graph change -> change detection

The candidate state machine is respected: every trusted record is
created by an explicit review action; POSSIBLE_MATCH is never
auto-confirmed; candidate information never enters the trusted graph.
All review writes are committed before the graph/analytics reads, so
the assertions observe the true trusted state.
"""

from app.services.graph.builder import build_trusted_graph
from app.services.graph.model import entity_node_id
from app.tests.conftest import make_txt_bytes, upload_bytes

TEXT = (
    "DEMO DATA test. Arjun Mehta was arrested during Operation Bluewater in "
    "Mumbai on 15 June 2026. The case has been registered as Case CASE-001 "
    "with number NCB/MUM/123/2026. Arjun Mehta was questioned in connection "
    "with Case CASE-001."
)


def _pending(client):
    return [
        c for c in client.get("/candidates").json()["items"] if c["status"] == "PENDING"
    ]


def test_full_investigation_workflow(client, db):
    # ------------------------------------------------------------------
    # document -> processing -> evidence -> candidates
    # ------------------------------------------------------------------
    response = upload_bytes(client, "investigation.txt", make_txt_bytes(TEXT))
    assert response.status_code == 201
    body = response.json()
    document = body["document"]
    assert body["duplicate_of"] is None
    assert len(document["sha256_hash"]) == 64
    assert document["processing_status"] in ("PROCESSED", "REVIEW_REQUIRED")

    pending = _pending(client)
    assert pending, "expected candidates after processing"
    assert any(
        c["evidence"] is not None and c["evidence"]["exact_text"] for c in pending
    ), "candidates must carry evidence quotes"

    # ------------------------------------------------------------------
    # validation (human review): confirm the person first
    # ------------------------------------------------------------------
    arjun_candidates = [
        c for c in pending
        if c["candidate_type"] == "ENTITY"
        and c["proposed_data"].get("name") == "Arjun Mehta"
    ]
    assert arjun_candidates, "expected an Arjun Mehta entity candidate"
    confirm = client.post(
        f"/candidates/{arjun_candidates[0]['candidate_id']}/confirm",
        json={"reviewed_by": "integration-test", "reason": "integration test"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "CONFIRMED"

    people = client.get("/entities?entity_type=PERSON").json()["items"]
    arjun = next(e for e in people if e["canonical_name"] == "Arjun Mehta")
    assert arjun["status"] == "ACTIVE"

    # Snapshot 1 — the trusted graph contains only the confirmed person
    # (the rest of the document is still PENDING and must not appear).
    snap1 = client.post("/snapshots", json={"label": "after person confirm"}).json()
    assert snap1["node_count"] == 1
    assert snap1["edge_count"] == 0

    # ------------------------------------------------------------------
    # validation: review the remaining candidates from the same document
    # ------------------------------------------------------------------
    # Case matches first: the official case number is the strongest
    # identifier, so facts/events confirmed afterwards link to the REAL
    # case record instead of creating a fresh case-name-only one.
    for candidate in _pending(client):
        if candidate["candidate_type"] != "CASE_MATCH":
            continue
        resp = client.post(
            f"/candidates/{candidate['candidate_id']}/confirm",
            json={"reviewed_by": "integration-test", "reason": "integration test"},
        )
        assert resp.status_code == 200, (candidate["candidate_type"], candidate["proposed_data"], resp.text)

    # Remaining candidates in creation order.
    for candidate in _pending(client):
        proposed = candidate["proposed_data"] or {}
        if (
            candidate["candidate_type"] == "RELATIONSHIP"
            and proposed.get("relationship_type") == "POSSIBLE_MATCH"
        ):
            # POSSIBLE_MATCH always stays PENDING until a human acts.
            continue
        resp = client.post(
            f"/candidates/{candidate['candidate_id']}/confirm",
            json={"reviewed_by": "integration-test", "reason": "integration test"},
        )
        assert resp.status_code == 200, (candidate["candidate_type"], proposed, resp.text)
    assert _pending(client) == [], "no reviewable candidate may be left unconfirmed"

    # ------------------------------------------------------------------
    # snapshot 2 + change detection (persisted + retrievable)
    # ------------------------------------------------------------------
    snap2 = client.post("/snapshots", json={"label": "after full review"}).json()
    assert snap2["version"] == 2
    assert snap2["node_count"] > snap1["node_count"]

    comparison = client.post(
        "/changes/compare",
        json={
            "previous_snapshot_id": snap1["snapshot_id"],
            "current_snapshot_id": snap2["snapshot_id"],
        },
    ).json()
    categories = {c["category"] for c in comparison["changes"]}
    assert "NEW_ENTITY" in categories
    assert "NEW_RELATIONSHIP" in categories
    assert "NETWORK_GROWTH" in categories
    assert comparison["total"] == (
        comparison["major"] + comparison["moderate"] + comparison["minor"]
    )

    # Part A: the detected changes are persisted and retrievable on the
    # snapshot that was compared.
    persisted = client.get(f"/snapshots/{snap2['snapshot_id']}/changes").json()
    assert persisted["total"] == comparison["total"]
    assert {c["category"] for c in persisted["items"]} == categories
    assert any(
        c["category"] == "NEW_ENTITY" and c["kind"] == "added" for c in persisted["items"]
    )
    assert any(c["category"] == "NETWORK_GROWTH" for c in persisted["items"])

    # ------------------------------------------------------------------
    # trusted graph + analytics + provenance (reads after commits)
    # ------------------------------------------------------------------
    nodes, edges = build_trusted_graph(db)
    arjun_node = next(n for n in nodes.values() if n.name == "Arjun Mehta")
    assert arjun_node.type == "PERSON"
    op_node = next(n for n in nodes.values() if n.name == "Operation Bluewater")
    assert any(n.type == "LOCATION" and n.name == "Mumbai" for n in nodes.values())
    assert any(n.type == "EVENT" for n in nodes.values())
    assert any(
        n.type == "CASE" and n.case_number == "NCB/MUM/123/2026"
        for n in nodes.values()
    )

    arrest_edges = [
        e for e in edges
        if e.relationship_type == "ARRESTED_IN"
        and e.source == arjun_node.id
        and e.target == op_node.id
    ]
    assert arrest_edges, "the confirmed arrest relationship must be a trusted edge"

    # Ego graph (1-hop) and shortest path through the API. The path edges
    # are structured (source/target/relationship_type), and the direct
    # Arjun -> Operation Bluewater hop is distance 1.
    ego = client.get(f"/graph/entity/{arjun['entity_id']}?hops=1").json()
    assert any(n["id"] == arjun_node.id for n in ego["nodes"])
    assert any(n["id"] == op_node.id for n in ego["nodes"])
    assert any(e["relationship_type"] == "ARRESTED_IN" for e in ego["edges"])

    path = client.get(
        f"/graph/path?source={arjun['entity_id']}&target={op_node.entity_id}"
    ).json()
    assert path["connected"] is True
    assert path["distance"] == 1
    assert len(path["edges"]) == 1
    hop = path["edges"][0]
    assert hop["source"] == entity_node_id(arjun["entity_id"])
    assert hop["target"] == op_node.id
    assert hop["relationship_type"] == "ARRESTED_IN"

    # Provenance: the arrest edge resolves to evidence + original document.
    prov = client.get(
        f"/graph/provenance/relationship/{arrest_edges[0].relationship_id}"
    ).json()
    assert prov["relationship_type"] == "ARRESTED_IN"
    assert prov["classification"] == "DIRECT"
    assert prov["evidence"] and prov["evidence"]["exact_text"]
    assert prov["document"] and prov["document"]["filename"] == "investigation.txt"

    # ------------------------------------------------------------------
    # search / timeline / cross-case / priority
    # ------------------------------------------------------------------
    search = client.get("/search?q=Arjun").json()
    assert any(e["canonical_name"] == "Arjun Mehta" for e in search["people"])

    timeline = client.get("/timeline/global").json()
    event_entry = next(
        e for e in timeline["items"]
        if e["kind"] == "event" and e["title"].startswith("Arrest of Arjun Mehta")
    )
    assert event_entry["date"] == "2026-06-15"
    assert event_entry["date_precision"] == "DAY"

    cross = client.get(f"/cross-case/entity/{arjun['entity_id']}").json()
    assert cross["case_count"] >= 1
    assert any(c["case_number"] == "NCB/MUM/123/2026" for c in cross["cases"])

    priority = client.get(f"/priority/{arjun['entity_id']}").json()
    assert 0.0 <= priority["total"] <= 100.0
    assert priority["breakdown"]["case_relevance"]["score"] > 0.0
    assert "not" in priority["disclaimer"].lower()

    # ------------------------------------------------------------------
    # audit trail: the review actions were recorded
    # ------------------------------------------------------------------
    audit = client.get("/audit").json()["items"]
    actions = {a["action"] for a in audit}
    assert "CONFIRM" in actions
    assert "CREATE" in actions
