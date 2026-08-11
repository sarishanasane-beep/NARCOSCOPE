"""PROMPT 2 PART 3 + PART 4 — WORKSPACES + ANNOTATIONS TESTS.

Covers workspace creation/pins (validated, idempotent), bookmarks
(deduped, existence-validated), investigator notes (annotations only —
never auto-promoted to facts/evidence), saved searches (re-run
through the one global query engine), and the Part 4 FINAL
INVESTIGATION WORKSPACE overview (pins resolved to current trusted
data + priority + saved searches + notes in one endpoint).
"""

import uuid

from app.models.fact import FACT_STATUS_CONFIRMED, Fact
from app.tests import graph_helpers as h


def _make_workspace(client, name="Mumbai Network Investigation"):
    resp = client.post("/workspaces", json={"name": name, "created_by": "tester"})
    assert resp.status_code == 201
    return resp.json()


def test_workspace_crud_and_pins(client, db):
    person = h.person(db, name="Suresh Patil")
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    db.commit()
    workspace = _make_workspace(client)
    assert workspace["name"] == "Mumbai Network Investigation"
    assert workspace["pins"] == []

    added = client.post(
        f"/workspaces/{workspace['workspace_id']}/pins",
        json={"kind": "entity", "id": person.entity_id, "name": "Suresh Patil"},
    ).json()
    assert added["pins"][0]["id"] == person.entity_id
    # Idempotent — the same pin is not duplicated.
    added_again = client.post(
        f"/workspaces/{workspace['workspace_id']}/pins",
        json={"kind": "entity", "id": person.entity_id},
    ).json()
    assert len(added_again["pins"]) == 1
    client.post(
        f"/workspaces/{workspace['workspace_id']}/pins",
        json={"kind": "case", "id": case_row.case_id},
    )
    listed = client.get("/workspaces").json()
    assert listed["total"] == 1
    fetched = client.get(f"/workspaces/{workspace['workspace_id']}").json()
    assert len(fetched["pins"]) == 2

    updated = client.put(
        f"/workspaces/{workspace['workspace_id']}", json={"name": "Renamed"}
    ).json()
    assert updated["name"] == "Renamed"

    removed = client.delete(f"/workspaces/{workspace['workspace_id']}/pins/0").json()
    assert len(removed["pins"]) == 1

    resp = client.delete(f"/workspaces/{workspace['workspace_id']}")
    assert resp.status_code == 204
    assert client.get("/workspaces").json()["total"] == 0


def test_workspace_pin_validates_existence(client, db):
    workspace = _make_workspace(client)
    resp = client.post(
        f"/workspaces/{workspace['workspace_id']}/pins",
        json={"kind": "entity", "id": str(uuid.uuid4())},
    )
    assert resp.status_code == 422


def test_workspace_delete_requires_existing(client, db):
    resp = client.delete(f"/workspaces/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_bookmarks_dedupe_and_validate(client, db):
    person = h.person(db, name="Suresh Patil")
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    db.commit()
    first = client.post(
        "/bookmarks",
        json={"subject_kind": "person", "subject_id": person.entity_id,
              "subject_name": "Suresh Patil", "name": "Key person"},
    )
    assert first.status_code == 201
    bookmark = first.json()
    # person normalizes to entity; same subject -> same bookmark (dedupe).
    second = client.post(
        "/bookmarks",
        json={"subject_kind": "entity", "subject_id": person.entity_id},
    )
    assert second.status_code == 201
    assert second.json()["bookmark_id"] == bookmark["bookmark_id"]
    client.post(
        "/bookmarks",
        json={"subject_kind": "case", "subject_id": case_row.case_id},
    )
    listed = client.get("/bookmarks").json()
    assert listed["total"] == 2
    entities = client.get("/bookmarks?subject_kind=entity").json()
    assert entities["total"] == 1
    # Non-existent subject is rejected.
    bad = client.post(
        "/bookmarks",
        json={"subject_kind": "case", "subject_id": str(uuid.uuid4())},
    )
    assert bad.status_code == 422
    resp = client.delete(f"/bookmarks/{bookmark['bookmark_id']}")
    assert resp.status_code == 204
    assert client.get("/bookmarks").json()["total"] == 1


def test_notes_are_annotations_only(client, db):
    person = h.person(db, name="Suresh Patil")
    db.commit()
    resp = client.post(
        "/notes",
        json={"content": "Investigator hunch — verify timeline.",
              "subject_kind": "entity", "subject_id": person.entity_id, "created_by": "tester"},
    )
    assert resp.status_code == 201
    note = resp.json()
    listed = client.get(f"/notes?subject_kind=entity&subject_id={person.entity_id}").json()
    assert listed["total"] == 1
    updated = client.put(f"/notes/{note['note_id']}", json={"content": "Updated note."}).json()
    assert updated["content"] == "Updated note."
    # A note must NEVER create facts/evidence/graph rows automatically.
    assert db.query(Fact).filter(Fact.status == FACT_STATUS_CONFIRMED).count() == 0
    resp = client.delete(f"/notes/{note['note_id']}")
    assert resp.status_code == 204
    assert client.get("/notes").json()["total"] == 0


def test_saved_search_run_through_query_engine(client, db):
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    loc = h.location(db, name="Pune")
    ev = h.event(db, title="Seizure in Pune", event_type="SEIZURE", precision="DAY",
                 start="2026-06-15", case_row=case_row, location_entity=loc)
    person = h.person(db, name="Nikhil Desai")
    h.fact(db, person, "QUESTIONED_IN", case_row=case_row, event_row=ev)
    db.commit()
    resp = client.post(
        "/saved-searches",
        json={
            "name": "June seizures in Pune",
            "filters": {
                "location": "Pune",
                "event_type": "SEIZURE",
                "date_from": "2026-06-01",
                "date_to": "2026-06-30",
            },
            "created_by": "tester",
        },
    )
    assert resp.status_code == 201
    saved = resp.json()
    assert saved["filters"]["event_type"] == "SEIZURE"
    listed = client.get("/saved-searches").json()
    assert listed["total"] == 1
    # Re-run the saved query through the ONE global query engine.
    result = client.get(f"/saved-searches/{saved['saved_search_id']}/run").json()
    assert any(e["title"] == "Seizure in Pune" for e in result["events"])
    assert any(p["entity_id"] == person.entity_id for p in result["people"])
    resp = client.delete(f"/saved-searches/{saved['saved_search_id']}")
    assert resp.status_code == 204


def test_saved_search_rejects_unknown_filters(client, db):
    resp = client.post(
        "/saved-searches",
        json={"name": "Bad", "filters": {"bogus_filter": 1}},
    )
    assert resp.status_code == 422


def test_saved_search_get_and_missing_ids(client, db):
    resp = client.post(
        "/saved-searches",
        json={"name": "June seizures", "filters": {"event_type": "SEIZURE"}},
    )
    assert resp.status_code == 201
    saved = resp.json()
    fetched = client.get(f"/saved-searches/{saved['saved_search_id']}").json()
    assert fetched["name"] == "June seizures"
    assert fetched["filters"]["event_type"] == "SEIZURE"
    assert client.get(f"/saved-searches/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/saved-searches/{uuid.uuid4()}/run").status_code == 404
    assert client.delete(f"/saved-searches/{uuid.uuid4()}").status_code == 404


def test_bookmark_and_note_missing_ids(client, db):
    assert client.delete(f"/bookmarks/{uuid.uuid4()}").status_code == 404
    assert client.put(f"/notes/{uuid.uuid4()}", json={"content": "x"}).status_code == 404
    assert client.delete(f"/notes/{uuid.uuid4()}").status_code == 404


# ---------------------------------------------------------------------------
# PROMPT 2 PART 4 — FINAL INVESTIGATION WORKSPACE (overview)
# ---------------------------------------------------------------------------


def test_workspace_overview_aggregates_pins_priority_searches_notes(client, db):
    person = h.person(db, name="Suresh Patil")
    case_row = h.case(db, number="NCB/MUM/123/2026", name="CASE-001")
    loc = h.location(db, name="Mumbai")
    db.commit()

    workspace = _make_workspace(client, name="Mumbai Network Investigation")
    wid = workspace["workspace_id"]
    client.post(f"/workspaces/{wid}/pins", json={"kind": "entity", "id": person.entity_id})
    client.post(f"/workspaces/{wid}/pins", json={"kind": "case", "id": case_row.case_id})
    # Locations are keyed by location_id (the canonical Location primary
    # key used by the graph builder and /graph/location/{location_id}).
    client.post(f"/workspaces/{wid}/pins", json={"kind": "location", "id": loc.location.location_id})

    note = client.post(
        "/notes",
        json={"content": "Follow the Pune leads.", "subject_kind": "workspace",
              "subject_id": wid, "created_by": "tester"},
    ).json()
    saved = client.post(
        "/saved-searches",
        json={"name": "June seizures in Pune",
              "filters": {"location": "Pune", "event_type": "SEIZURE"}},
    ).json()
    bookmark = client.post(
        "/bookmarks",
        json={"subject_kind": "person", "subject_id": person.entity_id,
              "subject_name": "Suresh Patil"},
    ).json()

    resp = client.get(f"/workspaces/{wid}/overview")
    assert resp.status_code == 200
    overview = resp.json()

    # Pins are resolved against the CURRENT trusted database.
    by_kind = {p["kind"]: p for p in overview["pins"]}
    assert by_kind["entity"]["name"] == "Suresh Patil"
    assert by_kind["entity"]["exists"] is True
    assert by_kind["case"]["name"] == "CASE-001"
    assert by_kind["location"]["name"] == "Mumbai"
    assert by_kind["location"]["exists"] is True
    assert by_kind["location"]["entity_id"] == loc.entity_id

    # Investigation Priority covers pinned entities and location pins
    # (resolved to their underlying entity record).
    priority_ids = {p["entity_id"] for p in overview["priorities"]}
    assert person.entity_id in priority_ids
    assert loc.entity_id in priority_ids
    for p in overview["priorities"]:
        assert 0 <= p["total"] <= 100
        assert "breakdown" in p
        assert "NOT guilt" in p["disclaimer"]

    # Saved searches, bookmarks and workspace notes are aggregated.
    assert overview["saved_searches"][0]["saved_search_id"] == saved["saved_search_id"]
    assert overview["bookmarks"][0]["bookmark_id"] == bookmark["bookmark_id"]
    assert [n["note_id"] for n in overview["notes"]] == [note["note_id"]]
    assert overview["change_total"] >= 0


def test_workspace_overview_empty_workspace(client, db):
    workspace = _make_workspace(client, name="Fresh Investigation")
    resp = client.get(f"/workspaces/{workspace['workspace_id']}/overview")
    assert resp.status_code == 200
    overview = resp.json()
    assert overview["pins"] == []
    assert overview["changes"] == []
    assert overview["change_total"] == 0
    assert overview["priorities"] == []
    assert overview["saved_searches"] == []
    assert overview["bookmarks"] == []
    assert overview["notes"] == []


def test_workspace_overview_missing_workspace(client, db):
    assert client.get(f"/workspaces/{uuid.uuid4()}/overview").status_code == 404


def test_workspace_overview_deleted_pin_does_not_crash(client, db):
    """A pin whose trusted record was deleted resolves to exists=false
    (name preserved, no exception) — the investigator can still see and
    remove it."""
    person = h.person(db, name="Suresh Patil")
    db.commit()
    workspace = _make_workspace(client, name="Aftermath Review")
    wid = workspace["workspace_id"]
    client.post(f"/workspaces/{wid}/pins", json={"kind": "entity", "id": person.entity_id})
    # Delete the underlying trusted record.
    db.delete(person)
    db.commit()
    resp = client.get(f"/workspaces/{wid}/overview")
    assert resp.status_code == 200
    pins = resp.json()["pins"]
    assert len(pins) == 1
    assert pins[0]["kind"] == "entity"
    assert pins[0]["id"] == person.entity_id
    assert pins[0]["exists"] is False
    assert resp.json()["priorities"] == []
