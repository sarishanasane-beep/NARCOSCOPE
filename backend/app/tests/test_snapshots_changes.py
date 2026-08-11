"""PROMPT 2 PART 3 — SNAPSHOTS + CHANGE DETECTION TESTS.

Covers:
- snapshot creation from confirmed data only (candidates excluded)
- multiple snapshots, immutability (never overwritten), deterministic hash
- comparison: NEW_ENTITY, NEW_RELATIONSHIP, REMOVED_RELATIONSHIP,
  CHANGED_RELATIONSHIP, NEW_SUPPORTING_EVIDENCE (never a new relationship)
- deterministic significance grouping (MAJOR/MODERATE/MINOR)
- the snapshot/change APIs
"""

from app.models.candidate import (
    CANDIDATE_STATUS_PENDING,
    CANDIDATE_TYPE_ENTITY,
    Candidate,
)
from app.services.graph.changes import compare_graph_data, summarize_changes
from app.services.graph.snapshots import (
    canonical_graph_data,
    create_snapshot,
    graph_hash,
    list_snapshots,
)
from app.tests import graph_helpers as h


def _snapshot(client, label=None):
    payload = {"label": label} if label else {}
    resp = client.post("/snapshots", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_snapshot_contains_only_confirmed_data(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    h.relationship(db, person, org, "PARTICIPATED_IN")
    # A pending candidate must never enter the snapshot.
    db.add(
        Candidate(
            candidate_id="cand-pending-1",
            candidate_type=CANDIDATE_TYPE_ENTITY,
            proposed_data={"name": "S. Patil", "entity_type": "PERSON"},
            reason="pending test candidate",
            status=CANDIDATE_STATUS_PENDING,
        )
    )
    db.commit()
    data = canonical_graph_data(db)
    names = {n["name"] for n in data["nodes"]}
    assert "Suresh Patil" in names
    assert "Blue Horizon Imports" in names
    assert "S. Patil" not in names
    assert len(data["edges"]) == 1
    assert data["edges"][0]["relationship_type"] == "PARTICIPATED_IN"


def test_snapshot_hash_deterministic_and_immutable(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    h.relationship(db, person, org, "PARTICIPATED_IN")
    db.commit()
    first = _snapshot(client, label="Snapshot 001")
    second = _snapshot(client, label="Snapshot 002")
    # Same trusted state -> same hash; different versions; never overwritten.
    assert first["graph_hash"] == second["graph_hash"]
    assert first["version"] == 1
    assert second["version"] == 2
    assert first["snapshot_id"] != second["snapshot_id"]
    snapshots = client.get("/snapshots").json()
    assert snapshots["total"] == 2
    assert {s["label"] for s in snapshots["items"]} == {"Snapshot 001", "Snapshot 002"}
    # The first snapshot is unchanged after the second was created.
    fetched = client.get(f"/snapshots/{first['snapshot_id']}").json()
    assert fetched["graph_hash"] == first["graph_hash"]


def test_new_entity_and_new_relationship_detected(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    h.relationship(db, person, org, "PARTICIPATED_IN")
    db.commit()
    first = _snapshot(client, "before")
    # New trusted entity + relationship.
    new_person = h.person(db, name="Nikhil Desai")
    h.relationship(db, new_person, org, "PARTICIPATED_IN")
    db.commit()
    second = _snapshot(client, "after")
    payload = client.post(
        "/changes/compare",
        json={"previous_snapshot_id": first["snapshot_id"], "current_snapshot_id": second["snapshot_id"]},
    ).json()
    categories = {c["category"] for c in payload["changes"]}
    assert "NEW_ENTITY" in categories
    assert "NEW_RELATIONSHIP" in categories
    assert payload["total"] >= 3  # 2 new entities + 1 new relationship + growth
    assert payload["major"] >= 2  # new persons are MAJOR
    # Persisted and retrievable.
    listed = client.get("/changes").json()
    assert listed["total"] >= payload["total"]


def test_removed_relationship_detected(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    rel = h.relationship(db, person, org, "PARTICIPATED_IN")
    db.commit()
    first = _snapshot(client, "with-edge")
    db.delete(rel)
    db.commit()
    second = _snapshot(client, "without-edge")
    payload = client.post(
        "/changes/compare",
        json={"previous_snapshot_id": first["snapshot_id"], "current_snapshot_id": second["snapshot_id"]},
    ).json()
    assert any(c["category"] == "REMOVED_RELATIONSHIP" for c in payload["changes"])
    # Entities remain (they still exist as trusted records) — only the edge
    # disappeared.
    assert not any(c["category"] == "REMOVED_ENTITY" for c in payload["changes"])


def test_removed_entity_detected(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    rel = h.relationship(db, person, org, "PARTICIPATED_IN")
    db.commit()
    first = _snapshot(client, "with-entity")
    # SQLite FK enforcement is ON: the referencing relationship must be
    # removed before the entity it points to.
    db.delete(rel)
    db.flush()
    db.delete(person)
    db.commit()
    second = _snapshot(client, "without-entity")
    payload = client.post(
        "/changes/compare",
        json={"previous_snapshot_id": first["snapshot_id"], "current_snapshot_id": second["snapshot_id"]},
    ).json()
    assert any(c["category"] == "REMOVED_ENTITY" for c in payload["changes"])


def test_new_supporting_evidence_not_new_relationship(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    doc_a = h.document(db, filename="a.txt")
    src_a = h.source(db, publisher="Press A")
    ev_a = h.evidence(db, doc_a, src_a, exact_text="First document.")
    rel = h.relationship(db, person, org, "PARTICIPATED_IN", evidence=ev_a)
    db.commit()
    first = _snapshot(client, "evidence-A")
    # A second document provides additional evidence for the SAME
    # relationship (same endpoints + type).
    doc_b = h.document(db, filename="b.txt")
    src_b = h.source(db, publisher="Press B")
    ev_b = h.evidence(db, doc_b, src_b, exact_text="Second document.")
    rel.evidence_id = ev_b.evidence_id
    db.commit()
    second = _snapshot(client, "evidence-B")

    payload = client.post(
        "/changes/compare",
        json={"previous_snapshot_id": first["snapshot_id"], "current_snapshot_id": second["snapshot_id"]},
    ).json()
    categories = {c["category"] for c in payload["changes"]}
    # The relationship gained evidence — this is NEW_SUPPORTING_EVIDENCE,
    # never a NEW_RELATIONSHIP.
    assert "NEW_SUPPORTING_EVIDENCE" in categories
    assert "NEW_RELATIONSHIP" not in categories
    evidence_changes = [c for c in payload["changes"] if c["category"] == "NEW_SUPPORTING_EVIDENCE"]
    assert len(evidence_changes) == 1
    assert evidence_changes[0]["significance"] == "MINOR"
    assert evidence_changes[0]["details"]["previous_evidence_id"] == ev_a.evidence_id
    assert evidence_changes[0]["details"]["new_evidence_id"] == ev_b.evidence_id


def test_changed_relationship_detected(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    doc = h.document(db, filename="a.txt")
    src = h.source(db, publisher="Press A")
    ev = h.evidence(db, doc, src, exact_text="Evidence.")
    rel = h.relationship(db, person, org, "PARTICIPATED_IN", evidence=ev, confidence=0.9)
    db.commit()
    first = _snapshot(client, "confidence-0.9")
    rel.confidence = 0.7
    db.commit()
    second = _snapshot(client, "confidence-0.7")
    payload = client.post(
        "/changes/compare",
        json={"previous_snapshot_id": first["snapshot_id"], "current_snapshot_id": second["snapshot_id"]},
    ).json()
    assert any(c["category"] == "CHANGED_RELATIONSHIP" for c in payload["changes"])
    assert not any(c["category"] == "NEW_RELATIONSHIP" for c in payload["changes"])


def test_summary_grouping_deterministic(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    h.relationship(db, person, org, "PARTICIPATED_IN")
    db.commit()
    first = _snapshot(client, "a")
    new_person = h.person(db, name="New Person")
    h.relationship(db, new_person, org, "ASSOCIATED_WITH")
    db.commit()
    second = _snapshot(client, "b")
    payload = client.post(
        "/changes/compare",
        json={"previous_snapshot_id": first["snapshot_id"], "current_snapshot_id": second["snapshot_id"]},
    ).json()
    assert payload["total"] == payload["major"] + payload["moderate"] + payload["minor"]
    assert payload["by_category"]["NEW_ENTITY"] >= 1
    assert payload["by_category"]["NEW_RELATIONSHIP"] >= 1
    assert payload["by_category"]["NETWORK_GROWTH"] == 1


def test_snapshot_missing_404(client, db):
    import uuid

    resp = client.get(f"/snapshots/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_snapshot_changes_endpoint_returns_persisted_rows(client, db):
    """Part A: /snapshots/{id}/changes returns the persisted change rows
    (the NEW_ENTITY + NETWORK_GROWTH pair from a real graph change)."""
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    h.relationship(db, person, org, "PARTICIPATED_IN")
    db.commit()
    first = _snapshot(client, "before")
    new_person = h.person(db, name="Nikhil Desai")
    h.relationship(db, new_person, org, "PARTICIPATED_IN")
    db.commit()
    second = _snapshot(client, "after")

    comparison = client.post(
        "/changes/compare",
        json={
            "previous_snapshot_id": first["snapshot_id"],
            "current_snapshot_id": second["snapshot_id"],
        },
    ).json()
    compare_categories = {c["category"] for c in comparison["changes"]}
    assert "NEW_ENTITY" in compare_categories
    assert "NETWORK_GROWTH" in compare_categories

    # The exact live-verification flow: GET the changes on the snapshot
    # that was compared — they must be persisted, not recomputed.
    persisted = client.get(f"/snapshots/{second['snapshot_id']}/changes").json()
    assert persisted["total"] == comparison["total"]
    categories = {c["category"] for c in persisted["items"]}
    assert categories == compare_categories
    entity_change = next(c for c in persisted["items"] if c["category"] == "NEW_ENTITY")
    assert entity_change["kind"] == "added"
    assert entity_change["significance"] == "MAJOR"  # a new PERSON
    growth = next(c for c in persisted["items"] if c["category"] == "NETWORK_GROWTH")
    assert growth["details"]["previous_nodes"] < growth["details"]["current_nodes"]
