"""CASE-SCOPED ANALYTICS + SAFE DUPLICATION TESTS.

Verifies:
- statistics / connected components / network clusters accept a case_id
  and never mix other cases / unrelated global records into the selected
  case's analysis,
- the location-network endpoint returns only trusted location data and
  never inferred proximity edges,
- duplicate detection is type-aware and normalizes names,
- merge repoints every reference and preserves provenance,
- merged records are excluded from active graph/stats/duplicate scans,
- keep-separate suppresses repeated flagging.
"""

from app.services.entities.duplicates import (
    detect_duplicates,
    duplicate_summary,
    entity_key,
    keep_separate,
    merge_cases,
    merge_entities,
)
from app.services.graph.analytics import connected_components, detect_clusters
from app.services.graph.service import graph_service
from app.tests.conftest import upload_bytes


def _confirm(client, candidate_type, **proposed_match):
    items = client.get("/candidates?limit=500").json()["items"]
    for c in items:
        if c["candidate_type"] != candidate_type or c.get("status") != "PENDING":
            continue
        p = c["proposed_data"] or {}
        if all(p.get(k) == v for k, v in proposed_match.items()):
            resp = client.post(f"/candidates/{c['candidate_id']}/confirm", json={"reason": "reviewed"})
            assert resp.status_code == 200, resp.text
            return c
    raise AssertionError(f"no {candidate_type} candidate matching {proposed_match}")


CASE_DOC = """\
NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT
FORMAT_VERSION: 2

CASE
CASE_ID: CASE-A
CASE_NAME: Case Alpha
CASE_TYPE: NARCOTICS_INVESTIGATION

ENTITY
ENTITY_ID: ENT-ORG
NAME: Org One
TYPE: ORGANIZATION

ENTITY
ENTITY_ID: ENT-LOC
NAME: Alpha City
TYPE: LOCATION

ENTITY
ENTITY_ID: ENT-DRUG
NAME: Cocaine
TYPE: DRUG

ENTITY
ENTITY_ID: ENT-PER
NAME: Mentioned Person
TYPE: PERSON
INVESTIGATIVE_STATUS: MENTIONED_ONLY

RELATIONSHIP
RELATIONSHIP_ID: REL-1
SOURCE: ENT-ORG
TARGET: CASE-A
TYPE: CONDUCTED_OPERATION

RELATIONSHIP
RELATIONSHIP_ID: REL-2
SOURCE: ENT-DRUG
TARGET: ENT-LOC
TYPE: SEIZED_AT

EVENT
EVENT_ID: EVT-1
NAME: Seizure event
TYPE: SEIZURE
LOCATION: Alpha City
DATE: 01 May 2026
"""

OTHER_DOC = """\
NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT
FORMAT_VERSION: 2

CASE
CASE_ID: CASE-B
CASE_NAME: Case Beta
CASE_TYPE: NARCOTICS_INVESTIGATION

ENTITY
ENTITY_ID: ENT-OTHER
NAME: Beta Location
TYPE: LOCATION

ENTITY
ENTITY_ID: ENT-DRUG2
NAME: Heroin
TYPE: DRUG

RELATIONSHIP
RELATIONSHIP_ID: REL-B1
SOURCE: ENT-DRUG2
TARGET: ENT-OTHER
TYPE: SEIZED_AT
"""


def _confirm_full_doc(client, text: str, filename: str):
    upload_bytes(client, filename, text.encode("utf-8"))
    _confirm(client, "CASE_MATCH")
    for c in client.get("/candidates?limit=500").json()["items"]:
        if c.get("status") != "PENDING":
            continue
        if c["candidate_type"] in ("ENTITY", "LOCATION", "RELATIONSHIP", "EVENT"):
            client.post(f"/candidates/{c['candidate_id']}/confirm", json={"reason": "reviewed"})
    cases = client.get("/cases").json()["items"]
    return cases[0]["case_id"]


# ---------------------------------------------------------------------------
# Case-scoped analytics (REQ 12-14)
# ---------------------------------------------------------------------------


def test_case_scoped_stats(client, db):
    case_a = _confirm_full_doc(client, CASE_DOC, "case_a.txt")
    _confirm_full_doc(client, OTHER_DOC, "case_b.txt")

    scoped = client.get(f"/graph/stats?case_id={case_a}").json()
    assert scoped["scope"] == "case"
    assert scoped["total_nodes"] == scoped["nodes_by_type"].get("CASE", 0) + sum(
        scoped["nodes_by_type"].get(t, 0)
        for t in ("PERSON", "ORGANIZATION", "LOCATION", "DRUG", "EVENT")
    )
    # Case Alpha graph: 1 case + 4 entities + 1 event = 6 nodes.
    # Edges: 2 explicit relationships + event PART_OF + event OCCURRED_IN = 4.
    assert scoped["total_nodes"] == 6
    assert scoped["total_edges"] == 4
    # Heroin / Beta Location (another case) must NOT leak in.
    assert scoped["nodes_by_type"].get("DRUG", 0) == 1  # only Cocaine

    # Global stats include both cases.
    global_stats = client.get("/graph/stats").json()
    assert global_stats["scope"] == "global"
    assert global_stats["total_nodes"] > scoped["total_nodes"]


def test_case_scoped_components(client, db):
    case_a = _confirm_full_doc(client, CASE_DOC, "case_a.txt")
    _confirm_full_doc(client, OTHER_DOC, "case_b.txt")

    global_comps = connected_components(db)
    scoped_comps = connected_components(db, case_id=case_a)
    assert len(scoped_comps) <= len(global_comps)
    # Every scoped node belongs to Case Alpha.
    scoped_names = {n["name"] for comp in scoped_comps for n in comp["nodes"]}
    assert "Cocaine" in scoped_names
    assert "Heroin" not in scoped_names
    assert "Beta Location" not in scoped_names


def test_case_scoped_clusters(client, db):
    case_a = _confirm_full_doc(client, CASE_DOC, "case_a.txt")
    _confirm_full_doc(client, OTHER_DOC, "case_b.txt")

    scoped = detect_clusters(db, case_id=case_a)
    all_names = {n for cl in scoped for n in cl["geographic_distribution"]}
    assert "Alpha City" in all_names
    assert "Beta Location" not in all_names


def test_location_network_trusted_only(client):
    case_a = _confirm_full_doc(client, CASE_DOC, "case_a.txt")
    loc = client.get(f"/graph/case/{case_a}/locations").json()
    assert loc["total_locations"] >= 1
    names = {n["name"] for n in loc["locations"]}
    assert "Alpha City" in names
    assert "Beta Location" not in names
    # Explicit location relationship exists (Cocaine SEIZED_AT Alpha City).
    assert loc["total_location_relationships"] >= 1
    rel_names = {
        e.get("relationship_type") for e in loc["location_relationships"]
    }
    assert "SEIZED_AT" in rel_names
    # No inferred NEAR / SAME_CITY edges are ever present.
    assert not rel_names & {"NEAR", "LOCATED_NEAR", "SAME_CITY", "SAME_DISTRICT", "SAME_REGION"}
    # Event with an explicit location link is reported.
    assert loc["total_events_with_locations"] >= 1


def test_stats_404_for_missing_case(client):
    assert client.get("/graph/stats?case_id=nope").status_code == 404
    assert client.get("/graph/analytics/components?case_id=nope").status_code == 404
    assert client.get("/graph/case/nope/locations").status_code == 404


# ---------------------------------------------------------------------------
# Duplicate detection (REQ 72-76, 85, 97)
# ---------------------------------------------------------------------------


def test_entity_key_type_aware_and_normalized():
    assert entity_key("PERSON", " Mumbai ") == "PERSON|mumbai"
    assert entity_key("LOCATION", "Mumbai") == "LOCATION|mumbai"
    assert entity_key("PERSON", "Mumbai") != entity_key("LOCATION", "Mumbai")
    assert entity_key("DRUG", "Cocaine") == entity_key("drug", " COCAINE ")


def test_duplicate_entities_detected(client, db):
    from app.models.entity import ENTITY_TYPE_LOCATION, ENTITY_TYPE_PERSON
    from app.services.entities.resolution import create_entity

    create_entity(db, entity_type=ENTITY_TYPE_LOCATION, canonical_name="Mumbai", user="tester")
    create_entity(db, entity_type=ENTITY_TYPE_LOCATION, canonical_name=" mumbai ", user="tester")
    create_entity(db, entity_type=ENTITY_TYPE_PERSON, canonical_name="Mumbai", user="tester")
    db.commit()

    groups = detect_duplicates(db, kind="entity")
    location_group = next(g for g in groups if g["kind"] == "entity" and g["entity_type"] == "LOCATION")
    assert location_group["classification"] == "POSSIBLE_DUPLICATE"
    assert len(location_group["records"]) == 2
    # Type-aware: PERSON+Mumbai is a different key — not merged with LOCATION.
    assert not [g for g in groups if g["entity_type"] == "PERSON" and len(g["records"]) > 1]


def test_confirmed_same_by_structured_id(client, db):
    from app.models.entity import ENTITY_TYPE_DRUG, Entity
    from app.services.entities.resolution import create_entity

    create_entity(db, entity_type=ENTITY_TYPE_DRUG, canonical_name="Cocaine",
                  structured_metadata={"entity_id": "ENT-COC"}, user="tester")
    create_entity(db, entity_type=ENTITY_TYPE_DRUG, canonical_name="Cocaine",
                  structured_metadata={"entity_id": "ENT-COC"}, user="tester")
    db.commit()
    groups = detect_duplicates(db, kind="entity")
    group = next(g for g in groups if g["entity_type"] == "DRUG")
    assert group["classification"] == "CONFIRMED_SAME"


def test_duplicate_cases_detected(client, db):
    from app.models.case import Case

    db.add(Case(case_id="c1", case_name="Operation WHITE STRIKE"))
    db.add(Case(case_id="c2", case_name="operation white strike "))
    db.commit()
    groups = detect_duplicates(db, kind="case")
    assert len(groups) == 1
    assert len(groups[0]["records"]) == 2


# ---------------------------------------------------------------------------
# Merge (REQ 77-84, 96)
# ---------------------------------------------------------------------------


def _make_document(db, document_id: str, filename: str):
    from app.models.document import Document

    db.add(Document(
        document_id=document_id, filename=filename, stored_filename=filename,
        file_type="txt", mime_type="text/plain", file_size=1, sha256_hash="x" * 64,
        storage_path=filename,
    ))
    db.flush()


def test_merge_entities_repoints_references_and_preserves_provenance(client, db):
    from app.models.entity import ENTITY_TYPE_ORGANIZATION, Entity
    from app.models.evidence import Evidence
    from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
    from app.services.entities.resolution import create_entity

    _make_document(db, "doc-a", "a.txt")
    _make_document(db, "doc-b", "b.txt")
    org_a = create_entity(db, entity_type=ENTITY_TYPE_ORGANIZATION, canonical_name="Narcotics Control Bureau",
                          document_id="doc-a", user="tester")
    org_b = create_entity(db, entity_type=ENTITY_TYPE_ORGANIZATION, canonical_name="Narcotics Control Bureau",
                          document_id="doc-b", user="tester")
    evidence = Evidence(evidence_id="ev-1", document_id="doc-a", exact_text="evidence text", text_start=0, text_end=3, page_number=1, extraction_method="deterministic_rules")
    db.add(evidence)
    db.add(Relationship(
        relationship_id="rel-1", source_entity_id=org_a.entity_id, target_entity_id=org_b.entity_id,
        relationship_type="CONDUCTED_OPERATION", status=REL_STATUS_CONFIRMED,
        evidence_id="ev-1", confidence=0.9, classification="DIRECT",
    ))
    db.commit()

    result = merge_entities(db, org_a.entity_id, org_b.entity_id, user="reviewer", note="same logical org")
    assert result["status"] == "merged"

    merged = db.get(Entity, org_b.entity_id)
    assert merged.status == "MERGED"
    assert merged.merged_into_id == org_a.entity_id

    rel = db.get(Relationship, "rel-1")
    assert rel.source_entity_id == org_a.entity_id
    assert rel.target_entity_id == org_a.entity_id
    assert rel.evidence_id == "ev-1"  # provenance preserved

    # Merged record no longer appears in the active graph.
    stats = graph_service.stats(db)
    names = None  # build check below
    from app.services.graph.builder import build_trusted_graph
    nodes, _ = build_trusted_graph(db)
    assert org_a.entity_id in {n.split(":")[-1] for n in nodes if n.startswith("entity:")}
    assert org_b.entity_id not in {n.split(":")[-1] for n in nodes if n.startswith("entity:")}
    # Stats count the canonical record only.
    assert stats["nodes_by_type"].get("ORGANIZATION", 0) >= 1


def test_merge_cases_repoints_references(client, db):
    from app.models.case import Case
    from app.models.entity import ENTITY_TYPE_ORGANIZATION, Entity
    from app.models.event import Event
    from app.models.fact import FACT_STATUS_CONFIRMED, Fact
    from app.models.relationship import REL_STATUS_CONFIRMED, Relationship
    from app.services.entities.resolution import create_entity

    db.add(Case(case_id="c-a", case_name="Operation WHITE STRIKE"))
    db.add(Case(case_id="c-b", case_name="Operation WHITE STRIKE"))
    e1 = create_entity(db, entity_type=ENTITY_TYPE_ORGANIZATION, canonical_name="Org One", user="tester")
    e2 = create_entity(db, entity_type=ENTITY_TYPE_ORGANIZATION, canonical_name="Org Two", user="tester")
    db.add(Relationship(relationship_id="r1", source_entity_id=e1.entity_id, target_entity_id=e2.entity_id,
                        relationship_type="X", status=REL_STATUS_CONFIRMED, case_id="c-b"))
    db.add(Event(event_id="ev1", event_type="SEIZURE", title="T", case_id="c-b"))
    db.add(Fact(fact_id="f1", subject_entity_id=e1.entity_id, predicate="P", case_id="c-b", status=FACT_STATUS_CONFIRMED))
    db.commit()

    merge_cases(db, "c-a", "c-b", user="reviewer")
    assert db.get(Case, "c-b").merged_into_id == "c-a"
    assert db.get(Relationship, "r1").case_id == "c-a"
    assert db.get(Event, "ev1").case_id == "c-a"
    assert db.get(Fact, "f1").case_id == "c-a"
    # Provenance/history preserved — records still exist.
    assert db.get(Relationship, "r1") is not None


def test_keep_separate_suppresses_flagging(client, db):
    from app.models.entity import ENTITY_TYPE_LOCATION, Entity
    from app.services.entities.resolution import create_entity

    loc_a = create_entity(db, entity_type=ENTITY_TYPE_LOCATION, canonical_name="Mumbai", user="tester")
    loc_b = create_entity(db, entity_type=ENTITY_TYPE_LOCATION, canonical_name="Mumbai", user="tester")
    db.commit()

    assert len(detect_duplicates(db, kind="entity")) == 1
    keep_separate(db, "entity", loc_a.entity_id, loc_b.entity_id, user="reviewer")
    db.commit()
    # The pair is no longer flagged (CONFIRMED DISTINCT decision recorded).
    assert detect_duplicates(db, kind="entity") == []


def test_duplicate_summary_counts(client, db):
    from app.models.entity import ENTITY_TYPE_LOCATION, Entity
    from app.services.entities.resolution import create_entity

    create_entity(db, entity_type=ENTITY_TYPE_LOCATION, canonical_name="Mumbai", user="tester")
    create_entity(db, entity_type=ENTITY_TYPE_LOCATION, canonical_name="Mumbai", user="tester")
    db.commit()
    summary = duplicate_summary(db)
    assert summary["possible_duplicate_groups"] >= 1
    assert summary["total_records"] >= 2
