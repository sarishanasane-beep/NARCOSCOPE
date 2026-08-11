"""PROMPT 2 PART 2 — GRAPH INTELLIGENCE TESTS.

Covers:
- analytics: centrality, connected components, clusters (neutral naming),
  shortest path (never via candidates)
- the reusable query engine: categorized search, date filters that respect
  precision (exact day vs month vs year vs unknown), location/type filters
- timelines: global / case / entity — event date kept separate from source
  publication date
- entity history: DOCUMENTED INVESTIGATION HISTORY across all cases
- cross-case connections and case overlap (canonical identity preserved)
"""

from datetime import date

from app.tests import graph_helpers as h
from app.services.graph.analytics import (
    betweenness_centrality,
    connected_components,
    degree_centrality,
    detect_clusters,
    shortest_path,
)
from app.services.graph.cross_case import case_overlap, cross_case_connections
from app.services.graph.model import entity_node_id
from app.services.search.history import entity_history
from app.services.search.query import InvestigationQuery, event_window, run_query
from app.services.search.timeline import case_timeline, entity_timeline, global_timeline
from app.utils.errors import NotFoundError, ValidationError


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def test_degree_and_betweenness_centrality_normalized(db):
    hub = h.person(db, name="Hub Person")
    leaf_a = h.person(db, name="Leaf A")
    leaf_b = h.person(db, name="Leaf B")
    h.relationship(db, hub, leaf_a, "ASSOCIATED_WITH")
    h.relationship(db, hub, leaf_b, "ASSOCIATED_WITH")
    db.commit()
    degree = degree_centrality(db)
    betweenness = betweenness_centrality(db)
    hub_id = entity_node_id(hub.entity_id)
    leaf_id = entity_node_id(leaf_a.entity_id)
    # Normalized degree: hub 2/2 = 1.0, leaf 1/2 = 0.5 (3 nodes).
    assert degree[hub_id] == 1.0
    assert degree[leaf_id] == 0.5
    assert 0.0 <= betweenness[hub_id] <= 1.0
    assert 0.0 <= betweenness[leaf_id] <= 1.0


def test_connected_components(db):
    a = h.person(db, name="A")
    b = h.person(db, name="B")
    isolated = h.person(db, name="Isolated")
    h.relationship(db, a, b, "ASSOCIATED_WITH")
    db.commit()
    components = connected_components(db)
    assert len(components) == 2
    sizes = sorted(c["node_count"] for c in components)
    assert sizes == [1, 2]


def test_clusters_use_neutral_naming(db):
    a = h.person(db, name="Cluster Alpha Person")
    b = h.person(db, name="Cluster Alpha Org")
    c = h.person(db, name="Cluster Beta Person")
    h.relationship(db, a, b, "ASSOCIATED_WITH")
    h.relationship(db, a, c, "ASSOCIATED_WITH")
    db.commit()
    clusters = detect_clusters(db)
    assert clusters
    for cluster in clusters:
        assert cluster["label"].startswith("Network Cluster ")
        assert cluster["node_count"] >= 1
        assert cluster["edge_count"] >= 0
        assert "associated_cases" in cluster
        assert "geographic_distribution" in cluster
        assert "growth_over_time" in cluster


def test_shortest_path_between_entities(db):
    a = h.person(db, name="Person A")
    org_x = h.org(db, name="Organization X")
    b = h.person(db, name="Person B")
    h.relationship(db, a, org_x, "ASSOCIATED_WITH")
    h.relationship(db, org_x, b, "ASSOCIATED_WITH")
    db.commit()
    path = shortest_path(db, a.entity_id, b.entity_id)
    assert path["connected"] is True
    assert path["distance"] == 2
    names = [n["name"] for n in path["path"]]
    assert names == ["Person A", "Organization X", "Person B"]
    assert len(path["edges"]) == 2
    # Person A -> Person B is NOT a direct relationship (2-hop).
    assert not any(e["relationship_type"] == "ASSOCIATED_WITH"
                   and e["source"] == entity_node_id(a.entity_id)
                   and e["target"] == entity_node_id(b.entity_id)
                   for e in path["edges"])


def test_shortest_path_no_path(db):
    a = h.person(db, name="Person A")
    b = h.person(db, name="Person B")
    db.commit()
    path = shortest_path(db, a.entity_id, b.entity_id)
    assert path["connected"] is False
    assert path["distance"] is None


def test_shortest_path_never_uses_candidate_relationships(db):
    a = h.person(db, name="Person A")
    b = h.person(db, name="Person B")
    from app.models.relationship import REL_STATUS_CANDIDATE

    h.relationship(db, a, b, "ASSOCIATED_WITH", status=REL_STATUS_CANDIDATE)
    db.commit()
    path = shortest_path(db, a.entity_id, b.entity_id)
    assert path["connected"] is False


# ---------------------------------------------------------------------------
# Query engine
# ---------------------------------------------------------------------------


def test_query_engine_categorized_results(client, db):
    person = h.person(db, name="Arjun Mehta")
    org = h.org(db, name="Blue Horizon Imports")
    loc = h.location(db, name="Mumbai")
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    ev = h.event(db, title="Operation Bluewater", precision="DAY",
                 start="2026-06-15", case_row=case_row, location_entity=loc)
    h.relationship(db, person, org, "PARTICIPATED_IN", event_row=ev, case_row=case_row)
    db.commit()
    result = run_query(db, InvestigationQuery(q="Arjun"))
    assert any(e["entity_id"] == person.entity_id and e["entity_type"] == "PERSON"
               for e in result["people"])
    result = run_query(db, InvestigationQuery(case_number="NCB/MUM/123/2026"))
    assert any(c["case_id"] == case_row.case_id for c in result["cases"])
    result = run_query(db, InvestigationQuery(q="Operation Bluewater"))
    assert any(e["event_id"] == ev.event_id for e in result["events"])


def test_query_location_filter_links_people(client, db):
    loc = h.location(db, name="Pune")
    person = h.person(db, name="Vikram Jadhav")
    ev = h.event(db, title="Seizure at Pune", event_type="SEIZURE", precision="DAY",
                 start="2026-06-15", location_entity=loc)
    h.relationship(db, person, loc, "RESIDES_IN")
    h.fact(db, person, "PARTICIPATED_IN", event_row=ev)
    db.commit()
    result = run_query(db, InvestigationQuery(location="Pune", event_type="SEIZURE"))
    assert any(e["title"] == "Seizure at Pune" for e in result["events"])
    assert any(p["entity_id"] == person.entity_id for p in result["people"])
    # The matched location itself is surfaced.
    assert any(l["entity_id"] == loc.entity_id for l in result["locations"])


def test_date_filter_exact_day_matches_day_precision_only(client, db):
    day_event = h.event(db, title="Exact Day Event", precision="DAY", start="2026-06-15")
    month_event = h.event(db, title="June Month Event", precision="MONTH", start="2026-06-01")
    year_event = h.event(db, title="2025 Year Event", precision="YEAR", start="2025-01-01")
    unknown_event = h.event(db, title="Unknown Date Event", precision="UNKNOWN", start=None)
    db.commit()
    exact = run_query(
        db,
        InvestigationQuery(date_from="2026-06-15", date_to="2026-06-15"),
    )
    titles = {e["title"] for e in exact["events"]}
    # A MONTH-precision event must NOT be claimed to have happened on an
    # exact day; UNKNOWN is never matched.
    assert "Exact Day Event" in titles
    assert "June Month Event" not in titles
    assert "2025 Year Event" not in titles
    assert "Unknown Date Event" not in titles


def test_date_filter_month_and_year_ranges(db):
    month_event = h.event(db, title="June Month Event", precision="MONTH", start="2026-06-01")
    year_event = h.event(db, title="2025 Year Event", precision="YEAR", start="2025-01-01")
    db.commit()
    june = run_query(
        db, InvestigationQuery(date_from="2026-06-01", date_to="2026-06-30")
    )
    assert any(e["title"] == "June Month Event" for e in june["events"])
    assert not any(e["title"] == "2025 Year Event" for e in june["events"])
    year = run_query(
        db, InvestigationQuery(date_from="2025-01-01", date_to="2025-12-31")
    )
    assert any(e["title"] == "2025 Year Event" for e in year["events"])
    assert not any(e["title"] == "June Month Event" for e in year["events"])


def test_event_window_respects_precision(db):
    day = h.event(db, title="Day", precision="DAY", start="2026-06-15")
    month = h.event(db, title="Month", precision="MONTH", start="2026-06-01")
    year = h.event(db, title="Year", precision="YEAR", start="2025-01-01")
    rng = h.event(db, title="Range", precision="RANGE", start="2026-06-10", end="2026-06-15")
    unknown = h.event(db, title="Unknown", precision="UNKNOWN", start=None)
    db.commit()
    assert event_window(day) == (date(2026, 6, 15), date(2026, 6, 15))
    assert event_window(month) == (date(2026, 6, 1), date(2026, 6, 30))
    assert event_window(year) == (date(2025, 1, 1), date(2025, 12, 31))
    assert event_window(rng) == (date(2026, 6, 10), date(2026, 6, 15))
    assert event_window(unknown) is None


def test_query_combined_filters(client, db):
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    loc = h.location(db, name="Pune")
    ev = h.event(db, title="Seizure at Pune", event_type="SEIZURE", precision="DAY",
                 start="2026-06-15", case_row=case_row, location_entity=loc)
    person = h.person(db, name="Nikhil Desai")
    h.fact(db, person, "QUESTIONED_IN", case_row=case_row, event_row=ev)
    db.commit()
    result = run_query(
        db,
        InvestigationQuery(
            location="Pune",
            event_type="SEIZURE",
            date_from="2026-06-01",
            date_to="2026-06-30",
            q="Desai",
        ),
    )
    assert any(e["event_id"] == ev.event_id for e in result["events"])
    assert any(p["entity_id"] == person.entity_id for p in result["people"])


def test_query_invalid_date_rejected(client, db):
    import pytest

    with pytest.raises(ValidationError):
        run_query(db, InvestigationQuery(date_from="not-a-date"))


# ---------------------------------------------------------------------------
# Timelines
# ---------------------------------------------------------------------------


def test_global_timeline_sorts_and_separates_dates(client, db):
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001", )
    case_row.start_date = date(2026, 1, 5)
    doc = h.document(db, filename="press.txt", publication_date=date(2026, 7, 1))
    src = h.source(db, publisher="Demo Press", publication_date=date(2026, 7, 1))
    evidence = h.evidence(db, doc, src, exact_text="Operation happened in June.")
    ev = h.event(db, title="Operation Bluewater", precision="MONTH",
                 start="2026-06-01", case_row=case_row)
    person = h.person(db, name="Suresh Patil")
    h.fact(db, person, "PARTICIPATED_IN", event_row=ev, evidence=evidence)
    h.confirmed_event_candidate(db, ev.title, evidence)
    db.commit()
    entries = global_timeline(db)
    dates = [e["date"] for e in entries]
    assert dates == sorted(d for d in dates if d)
    event_entry = next(e for e in entries if e["kind"] == "event")
    # Event date (June 2026, MONTH precision) is separate from publication.
    assert event_entry["date"] == "2026-06-01"
    assert event_entry["date_precision"] == "MONTH"
    assert event_entry["source_publication_date"] == "2026-07-01"


def test_entity_timeline_spans_all_cases(client, db):
    person = h.person(db, name="Suresh Patil")
    case_a = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    case_b = h.case(db, number="NCB/MUM/456/2026", name="CASE-002")
    ev_a = h.event(db, title="Operation Alpha", precision="DAY", start="2026-06-15", case_row=case_a)
    ev_b = h.event(db, title="Operation Beta", precision="DAY", start="2026-07-20", case_row=case_b)
    h.fact(db, person, "PARTICIPATED_IN", event_row=ev_a, case_row=case_a)
    h.fact(db, person, "PARTICIPATED_IN", event_row=ev_b, case_row=case_b)
    db.commit()
    entries = entity_timeline(db, person.entity_id)
    titles = {e["title"] for e in entries}
    assert "Operation Alpha" in titles
    assert "Operation Beta" in titles
    ordered = [e["date"] for e in entries if e["date"]]
    assert ordered == sorted(ordered)


def test_case_timeline_separates_event_and_publication(client, db):
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    case_row.start_date = date(2026, 1, 5)
    doc = h.document(db, filename="court.txt", publication_date=date(2026, 8, 1))
    src = h.source(db, publisher="Court", source_type="COURT_PUBLIC_RECORD")
    evidence = h.evidence(db, doc, src, exact_text="Court proceeding recorded.")
    ev = h.event(db, title="Court Proceeding", event_type="COURT_PROCEEDING",
                 precision="DAY", start="2026-06-15", case_row=case_row)
    person = h.person(db, name="Vikram Jadhav")
    h.fact(db, person, "QUESTIONED_IN", case_row=case_row, event_row=ev, evidence=evidence)
    h.confirmed_event_candidate(db, ev.title, evidence)
    db.commit()
    entries = case_timeline(db, case_row.case_id)
    assert any(e["kind"] == "case" and e["date"] == "2026-01-05" for e in entries)
    event_entry = next(e for e in entries if e["kind"] == "event")
    assert event_entry["date"] == "2026-06-15"
    assert event_entry["date_precision"] == "DAY"
    assert event_entry["source_publication_date"] == "2026-08-01"


# ---------------------------------------------------------------------------
# Entity history / cross-case
# ---------------------------------------------------------------------------


def test_entity_history_documented_investigation(client, db):
    person = h.person(db, name="Suresh Patil", aliases=["S. Patil"])
    org = h.org(db, name="Blue Horizon Imports")
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    ev = h.event(db, title="Operation Bluewater", precision="DAY", start="2026-06-15", case_row=case_row)
    h.relationship(db, person, org, "PARTICIPATED_IN", event_row=ev, case_row=case_row)
    db.commit()
    history = entity_history(db, person.entity_id)
    assert history["documented_investigation_history"] is True
    assert history["entity"]["aliases"] == ["S. Patil"]
    assert history["case_count"] == 1
    assert history["cases"][0]["official_case_number"] == "NCB/MUM/123/2026"
    assert any(o["canonical_name"] == "Blue Horizon Imports" for o in history["organizations"])
    assert any(r["relationship_type"] == "PARTICIPATED_IN" for r in history["relationships"])
    # Neutral framing: no "criminal" label anywhere.
    assert not any("criminal" in key.lower() for key in history)


def test_cross_case_connections_one_entity_many_cases(client, db):
    person = h.person(db, name="Suresh Patil")
    case_a = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    case_b = h.case(db, number="NCB/MUM/456/2026", name="CASE-002")
    case_c = h.case(db, number="NCB/MUM/789/2026", name="CASE-003")
    for case_row in (case_a, case_b, case_c):
        h.fact(db, person, "QUESTIONED_IN", case_row=case_row)
    db.commit()
    result = cross_case_connections(db, person.entity_id)
    assert result["canonical_name"] == "Suresh Patil"
    assert result["case_count"] == 3
    numbers = {c["case_number"] for c in result["cases"]}
    assert numbers == {"NCB/MUM/123/2026", "NCB/MUM/456/2026", "NCB/MUM/789/2026"}


def test_case_overlap_detects_shared_entities(client, db):
    person = h.person(db, name="Suresh Patil")
    org = h.org(db, name="Blue Horizon Imports")
    case_a = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    case_b = h.case(db, number="NCB/MUM/456/2026", name="CASE-002")
    h.fact(db, person, "QUESTIONED_IN", case_row=case_a)
    h.fact(db, person, "QUESTIONED_IN", case_row=case_b)
    h.fact(db, org, "INVOLVED_IN", case_row=case_b)
    db.commit()
    overlaps = case_overlap(db)
    assert len(overlaps) == 1
    overlap = overlaps[0]
    pair = {overlap["case_a"]["case_id"], overlap["case_b"]["case_id"]}
    assert pair == {case_a.case_id, case_b.case_id}
    assert any(e["canonical_name"] == "Suresh Patil" for e in overlap["shared_entities"])
    # No criminal implication from overlap.
    assert "criminal" not in str(overlap).lower()


def test_history_endpoint_404(client, db):
    import uuid

    resp = client.get(f"/entities/{uuid.uuid4()}/history")
    assert resp.status_code == 404


def test_cross_case_entity_404(client, db):
    import uuid

    resp = client.get(f"/cross-case/entity/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_global_timeline_empty_database(client, db):
    """Empty DB -> safe empty timeline through the service and the API."""
    assert global_timeline(db) == []
    resp = client.get("/timeline/global").json()
    assert resp["total"] == 0
    assert resp["items"] == []


def test_global_timeline_unknown_precision(client, db):
    """An UNKNOWN-precision event renders as unknown — never a fake
    exact day."""
    h.event(db, title="Undated Event", precision="UNKNOWN", start=None)
    db.commit()
    entries = global_timeline(db)
    assert entries
    entry = entries[0]
    assert entry["kind"] == "event"
    assert entry["title"] == "Undated Event"
    assert entry["date"] is None
    assert entry["date_precision"] == "UNKNOWN"
    assert entry["source_publication_date"] is None
