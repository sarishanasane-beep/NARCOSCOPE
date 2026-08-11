"""PROMPT 2 PART 3 — INVESTIGATION PRIORITY TESTS.

Verifies the deterministic 0-100 score, the transparent breakdown, and
that the components respond to data: recency decays with time, centrality
grows with connections, source diversity grows with distinct sources,
case relevance responds to a selected case, and the total is always in
[0, 100]. The disclaimer is always present (never guilt/criminality).
"""

from datetime import datetime, timedelta, timezone

from app.services.graph.priority import (
    DECAY_CONSTANT_DAYS,
    priority_for_entity,
    priority_ranking,
)
from app.tests import graph_helpers as h


def test_priority_breakdown_shape_and_ranges(db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    doc = h.document(db, filename="a.txt")
    src = h.source(db, publisher="Press A", source_type="SECONDARY_SOURCE")
    ev = h.evidence(db, doc, src, exact_text="Evidence.")
    h.relationship(db, person, org, "PARTICIPATED_IN", case_row=case_row, evidence=ev)
    db.commit()
    priority = priority_for_entity(db, person.entity_id)
    assert 0.0 <= priority["total"] <= 100.0
    breakdown = priority["breakdown"]
    assert set(breakdown) == {
        "recency", "cross_cluster", "centrality", "case_relevance", "source_diversity",
    }
    assert 0.0 <= breakdown["recency"]["score"] <= 30.0
    assert 0.0 <= breakdown["cross_cluster"]["score"] <= 25.0
    assert 0.0 <= breakdown["centrality"]["score"] <= 20.0
    assert 0.0 <= breakdown["case_relevance"]["score"] <= 15.0
    assert 0.0 <= breakdown["source_diversity"]["score"] <= 10.0
    assert "not a probability of guilt" in priority["disclaimer"].lower() or \
        "not guilt" in priority["disclaimer"].lower()


def test_recency_decays_over_time(db):
    fresh = h.person(db, name="Fresh Person")
    old = h.person(db, name="Old Person")
    db.commit()
    fresh_priority = priority_for_entity(db, fresh.entity_id)
    # Simulate no activity for ~2 decay constants.
    old.updated_at = datetime.now(timezone.utc) - timedelta(days=2 * DECAY_CONSTANT_DAYS)
    db.commit()
    old_priority = priority_for_entity(db, old.entity_id)
    fresh_recency = fresh_priority["breakdown"]["recency"]["score"]
    old_recency = old_priority["breakdown"]["recency"]["score"]
    assert fresh_recency > old_recency
    # Fresh entity: ~30 (decay from 0 days). Old: clearly below half.
    assert fresh_recency > 25.0
    assert old_recency < 15.0


def test_centrality_increases_with_connections(db):
    hub = h.person(db, name="Hub Person")
    leaf = h.person(db, name="Leaf Person")
    a = h.person(db, name="Neighbor A")
    b = h.person(db, name="Neighbor B")
    c = h.person(db, name="Neighbor C")
    h.relationship(db, hub, a, "ASSOCIATED_WITH")
    h.relationship(db, hub, b, "ASSOCIATED_WITH")
    h.relationship(db, hub, c, "ASSOCIATED_WITH")
    h.relationship(db, leaf, a, "ASSOCIATED_WITH")
    db.commit()
    hub_priority = priority_for_entity(db, hub.entity_id)
    leaf_priority = priority_for_entity(db, leaf.entity_id)
    hub_centrality = hub_priority["breakdown"]["centrality"]["score"]
    leaf_centrality = leaf_priority["breakdown"]["centrality"]["score"]
    assert hub_centrality > leaf_centrality


def test_source_diversity_grows_with_distinct_sources(db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    doc_a = h.document(db, filename="a.txt")
    doc_b = h.document(db, filename="b.txt")
    src_a = h.source(db, publisher="Press A", source_type="OFFICIAL_GOVERNMENT")
    src_b = h.source(db, publisher="Press B", source_type="SECONDARY_SOURCE")
    ev_a = h.evidence(db, doc_a, src_a, exact_text="First.")
    ev_b = h.evidence(db, doc_b, src_b, exact_text="Second.")
    h.relationship(db, person, org, "PARTICIPATED_IN", evidence=ev_a)
    h.fact(db, person, "QUESTIONED_IN", object_entity=org, evidence=ev_b)
    db.commit()
    priority = priority_for_entity(db, person.entity_id)
    diversity = priority["breakdown"]["source_diversity"]
    assert diversity["score"] > 0.0
    assert set(diversity["distinct_publishers"]) == {"Press A", "Press B"}
    assert set(diversity["distinct_source_types"]) == {"OFFICIAL_GOVERNMENT", "SECONDARY_SOURCE"}


def test_case_relevance_selected_case(db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    case_a = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    case_b = h.case(db, number="NCB/MUM/456/2026", name="CASE-002")
    h.relationship(db, person, org, "PARTICIPATED_IN", case_row=case_a)
    h.fact(db, person, "QUESTIONED_IN", case_row=case_b)
    db.commit()
    in_case = priority_for_entity(db, person.entity_id, case_id=case_a.case_id)
    assert in_case["breakdown"]["case_relevance"]["score"] == 15.0
    in_other = priority_for_entity(db, person.entity_id, case_id=case_b.case_id)
    assert in_other["breakdown"]["case_relevance"]["score"] == 15.0
    unrelated = h.case(db, number="NCB/MUM/999/2026", name="CASE-999")
    db.commit()
    not_in = priority_for_entity(db, person.entity_id, case_id=unrelated.case_id)
    assert not_in["breakdown"]["case_relevance"]["score"] < 15.0


def test_priority_ranking_deterministic(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    h.relationship(db, person, org, "PARTICIPATED_IN", case_row=case_row)
    db.commit()
    ranking = priority_ranking(db, limit=10)
    assert ranking
    assert all(0.0 <= item["total"] <= 100.0 for item in ranking)
    totals = [item["total"] for item in ranking]
    assert totals == sorted(totals, reverse=True)
    assert all("breakdown" in item for item in ranking)
    # API surface.
    resp = client.get(f"/priority/{person.entity_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["entity_id"] == person.entity_id
    assert "breakdown" in payload
    assert "disclaimer" in payload
    ranking_resp = client.get("/priority/ranking?limit=5")
    assert ranking_resp.status_code == 200
    assert ranking_resp.json()["total"] >= 1


def test_priority_unknown_entity_404(client, db):
    import uuid

    resp = client.get(f"/priority/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_priority_ranking_empty_database(client, db):
    """Empty DB -> empty, deterministic ranking (no crash, no fabricated
    scores)."""
    ranking = client.get("/priority/ranking").json()
    assert ranking == {"total": 0, "items": []}
