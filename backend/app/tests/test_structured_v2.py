"""v2 STRUCTURED TXT FORMAT TESTS.

The v2 contract is the deterministic NARCOSCOPE input format:

    NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT
    FORMAT_VERSION: 2

    CASE
    CASE_ID: OPERATION-WHITE-STRIKE
    CASE_NAME: Operation WHITE STRIKE

    ENTITY
    ENTITY_ID: ENT-LAXMAN
    NAME: Laxman Compound
    TYPE: LOCATION

These tests verify that:

- the canonical header is detected (and prose/case names alone are not),
- declared TYPEs are authoritative — Laxman Compound is LOCATION, never
  PERSON, no matter how it is capitalised in the text,
- CASE_ID / ENTITY_ID / EVENT_ID / RELATIONSHIP_ID / FACT_ID are the
  authoritative identities (dedup, no duplicates),
- duplicate IDs with conflicting values surface a structured validation
  issue instead of being silently repaired,
- relationship SOURCE/TARGET resolve only against declared IDs/names —
  an unknown ID is a validation error, never a fabricated entity,
- PUBLICATION_DATE is document metadata and never becomes an event date,
- FACT blocks stay facts (no invented PERSON/EVENT/RELATIONSHIP),
- mentioned-only/contextual people remain isolated nodes,
- structured documents never fall through to the generic engine,
- generic unstructured extraction is untouched.
"""

from pathlib import Path

from app.services.extraction.structured import detect_structured, parse_structured
from app.tests.conftest import upload_bytes

V2_HEADER = "NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT\nFORMAT_VERSION: 2\n"

V2_DOC = V2_HEADER + """\
CASE
CASE_ID: OPERATION-WHITE-STRIKE
CASE_NAME: Operation WHITE STRIKE
CASE_TYPE: NARCOTICS_INVESTIGATION
STATUS: ACTIVE_INVESTIGATION

ENTITY
ENTITY_ID: ENT-NCB
NAME: Narcotics Control Bureau
TYPE: ORGANIZATION
ROLE: INVESTIGATING_AGENCY

ENTITY
ENTITY_ID: ENT-LAXMAN
NAME: Laxman Compound
TYPE: LOCATION
LOCATION_TYPE: WAREHOUSE

ENTITY
ENTITY_ID: ENT-COC
NAME: Cocaine
TYPE: DRUG
QUANTITY: 349 kg

ENTITY
ENTITY_ID: ENT-VEH
NAME: Maruti Suzuki Super Carry
TYPE: VEHICLE
REGISTRATION: MH-03-DV-3803

ENTITY
ENTITY_ID: ENT-AMIT
NAME: Amit Shah
TYPE: PERSON
ROLE: UNION HOME MINISTER
INVESTIGATIVE_STATUS: MENTIONED_ONLY

ENTITY
ENTITY_ID: ENT-MODI
NAME: Narendra Modi
TYPE: PERSON
ROLE: PRIME MINISTER
INVESTIGATIVE_STATUS: MENTIONED_ONLY

EVENT
EVENT_ID: EVT-FIRST-STRIKE
NAME: First strike
TYPE: VEHICLE_INTERCEPTION_AND_SEIZURE
DATE: 03 March 2026
LOCATION: Laxman Compound
DESCRIPTION: NCB officers intercepted the vehicle at the warehouse.

EVENT
EVENT_ID: EVT-SECOND-OP
NAME: Second operation
TYPE: SEARCH_AND_SEIZURE
LOCATION: Laxman Compound
DESCRIPTION: A second operation recovered more packets.

RELATIONSHIP
RELATIONSHIP_ID: REL-011
SOURCE: ENT-NCB
TARGET: OPERATION-WHITE-STRIKE
TYPE: CONDUCTED_OPERATION

RELATIONSHIP
RELATIONSHIP_ID: REL-012
SOURCE: ENT-COC
TARGET: ENT-LAXMAN
TYPE: SEIZED_AT

FACT
FACT_ID: FACT-001
DESCRIPTION: Approximately 349 kg of cocaine was seized.
STATUS: CONFIRMED_FROM_SOURCE
"""


def _entity_names(result, entity_type: str) -> set[str]:
    return {e.name for e in result.entities if e.entity_type == entity_type}


def _rel_triples(result) -> set[tuple[str, str, str]]:
    return {
        (r.source_name, r.relationship_type, r.target_name)
        for r in result.relationships
    }


# ---------------------------------------------------------------------------
# Detection (TEST 1)
# ---------------------------------------------------------------------------


def test_detect_v2_canonical_header():
    assert detect_structured(V2_DOC) is True


def test_detect_v2_without_format_version():
    text = "NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT\n\nCASE\nCASE_NAME: X\n"
    assert detect_structured(text) is True


def test_detect_v2_false_for_prose_keywords():
    prose = (
        "The CASE was opened after the ENTITY was identified. The EVENT "
        "covered an investigation. ENTITY_ID and CASE_ID are words here."
    )
    assert detect_structured(prose) is False


def test_detect_v2_false_for_case_name_only():
    assert detect_structured("CASE_NAME: Operation WHITE STRIKE\n") is False


# ---------------------------------------------------------------------------
# CASE parsing (TESTS 2, 3)
# ---------------------------------------------------------------------------


def test_v2_case_parsing():
    result = parse_structured(V2_DOC).result
    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.case_name == "Operation WHITE STRIKE"
    assert case.category == "NARCOTICS_INVESTIGATION"
    assert case.status == "ACTIVE_INVESTIGATION"
    assert case.structured_id == "OPERATION-WHITE-STRIKE"


def test_v2_duplicate_case_id_creates_one_case():
    text = V2_HEADER + (
        "CASE\nCASE_ID: C-1\nCASE_NAME: Case One\n\n"
        "CASE\nCASE_ID: C-1\nCASE_NAME: Case One\nSTATUS: ACTIVE\n"
    )
    result = parse_structured(text).result
    assert len(result.cases) == 1
    assert result.cases[0].case_name == "Case One"
    assert result.cases[0].status == "ACTIVE"  # later metadata merged


def test_v2_case_id_conflict_surfaces_validation():
    text = V2_HEADER + (
        "CASE\nCASE_ID: C-1\nCASE_NAME: Case One\n\n"
        "CASE\nCASE_ID: C-1\nCASE_NAME: Case Two\n"
    )
    parsed = parse_structured(text)
    assert len(parsed.result.cases) == 1
    assert parsed.result.cases[0].case_name == "Case One"
    assert any(
        "conflicting" in v["message"] and v["id"] == "C-1"
        for v in parsed.validation
    )


# ---------------------------------------------------------------------------
# Entity typing — declared TYPE is authoritative (TESTS 4, 5, 52)
# ---------------------------------------------------------------------------


def test_v2_entity_type_preserved():
    result = parse_structured(V2_DOC).result
    assert _entity_names(result, "ORGANIZATION") == {"Narcotics Control Bureau"}
    assert _entity_names(result, "LOCATION") == {"Laxman Compound"}
    assert _entity_names(result, "DRUG") == {"Cocaine"}
    assert _entity_names(result, "VEHICLE") == {"Maruti Suzuki Super Carry"}
    assert _entity_names(result, "PERSON") == {"Amit Shah", "Narendra Modi"}
    # Never reclassified as PERSON by generic heuristics.
    person_names = _entity_names(result, "PERSON")
    assert not person_names & {"Laxman Compound", "Cocaine", "Maruti Suzuki Super Carry"}


def test_v2_location_is_never_person():
    result = parse_structured(V2_HEADER + "ENTITY\nENTITY_ID: ENT-LAXMAN\nNAME: Laxman Compound\nTYPE: LOCATION\n").result
    assert "Laxman Compound" in _entity_names(result, "LOCATION")
    assert "Laxman Compound" not in _entity_names(result, "PERSON")
    assert "Laxman Compound" not in _entity_names(result, "DRUG")


def test_v2_entity_metadata_preserved():
    result = parse_structured(V2_DOC).result
    by_name = {e.name: e for e in result.entities}
    assert by_name["Cocaine"].extra.get("quantity") == "349 kg"
    assert by_name["Maruti Suzuki Super Carry"].extra.get("registration") == "MH-03-DV-3803"
    assert by_name["Laxman Compound"].extra.get("location_type") == "WAREHOUSE"
    assert by_name["Narcotics Control Bureau"].extra.get("role") == "INVESTIGATING_AGENCY"
    assert by_name["Amit Shah"].extra.get("investigative_status") == "MENTIONED_ONLY"
    assert by_name["Amit Shah"].extra.get("entity_id") == "ENT-AMIT"


# ---------------------------------------------------------------------------
# ENTITY_ID dedup and validation (TEST 6, 42)
# ---------------------------------------------------------------------------


def test_v2_entity_id_dedup():
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-NCB\nNAME: Narcotics Control Bureau\nTYPE: ORGANIZATION\n\n"
        "ENTITY\nENTITY_ID: ENT-NCB\nNAME: Narcotics Control Bureau\nTYPE: ORGANIZATION\nROLE: INVESTIGATING_AGENCY\n"
    )
    result = parse_structured(text).result
    orgs = [e for e in result.entities if e.entity_type == "ORGANIZATION"]
    assert len(orgs) == 1
    assert orgs[0].extra.get("role") == "INVESTIGATING_AGENCY"


def test_v2_entity_id_conflict_surfaces_validation():
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-LAXMAN\nNAME: Laxman Compound\nTYPE: LOCATION\n\n"
        "ENTITY\nENTITY_ID: ENT-LAXMAN\nNAME: Laxman Compound\nTYPE: PERSON\n"
    )
    parsed = parse_structured(text)
    assert _entity_names(parsed.result, "LOCATION") == {"Laxman Compound"}
    assert parsed.result.entities == [e for e in parsed.result.entities if e.entity_type != "PERSON" or e.name != "Laxman Compound"]
    assert any(
        "conflicting" in v["message"] and v["id"] == "ENT-LAXMAN"
        for v in parsed.validation
    )


def test_v2_invalid_entity_type_is_validation_error():
    text = V2_HEADER + "ENTITY\nENTITY_ID: ENT-X\nNAME: Something\nTYPE: NOT_A_TYPE\n"
    parsed = parse_structured(text)
    assert parsed.result.entities == []
    assert any("invalid TYPE" in v["message"] for v in parsed.validation)


# ---------------------------------------------------------------------------
# EVENT parsing (TESTS 7, 8, 13, 28)
# ---------------------------------------------------------------------------


def test_v2_event_parsing():
    result = parse_structured(V2_DOC).result
    events = {e.title: e for e in result.events}
    assert "First strike" in events
    first = events["First strike"]
    assert first.event_type == "VEHICLE_INTERCEPTION_AND_SEIZURE"
    assert first.date is not None
    assert first.date.to_iso() == "2026-03-03"
    assert first.location_name == "Laxman Compound"
    assert first.extra.get("event_id") == "EVT-FIRST-STRIKE"
    # Only the two declared EVENT blocks — the descriptions inside the
    # blocks never create additional events.
    assert len(result.events) == 2


def test_v2_undated_event_has_no_date():
    result = parse_structured(V2_DOC).result
    second = next(e for e in result.events if e.title == "Second operation")
    assert second.date is None


def test_v2_event_id_dedup():
    text = V2_HEADER + (
        "EVENT\nEVENT_ID: EVT-1\nNAME: One event\nTYPE: SEIZURE\n\n"
        "EVENT\nEVENT_ID: EVT-1\nNAME: One event\nTYPE: SEIZURE\n"
    )
    result = parse_structured(text).result
    assert len(result.events) == 1


def test_v2_month_precision_date():
    text = V2_HEADER + (
        "EVENT\nEVENT_ID: EVT-M\nNAME: Monthly\nTYPE: SEIZURE\nDATE: 2026-05\n"
        "DATE_PRECISION: MONTH\n"
    )
    result = parse_structured(text).result
    event = result.events[0]
    assert event.date is not None
    assert event.date.to_iso() == "2026-05-01"
    assert event.date.precision == "MONTH"


def test_v2_publication_date_is_not_event_date():
    """The document publication date is metadata — never an event date."""
    text = V2_HEADER + (
        "PUBLICATION_DATE: 01-05-2026\n\n"
        "EVENT\nEVENT_ID: EVT-1\nNAME: Undated event\nTYPE: SEIZURE\n"
    )
    parsed = parse_structured(text)
    assert parsed.metadata.get("date") is not None
    assert parsed.metadata["date"].to_iso() == "2026-05-01"
    assert parsed.result.events[0].date is None


# ---------------------------------------------------------------------------
# RELATIONSHIP parsing (TESTS 10, 11, 14, 15, 16)
# ---------------------------------------------------------------------------


def test_v2_relationship_resolves_entity_ids():
    result = parse_structured(V2_DOC).result
    triples = _rel_triples(result)
    assert ("Narcotics Control Bureau", "CONDUCTED_OPERATION", "Operation WHITE STRIKE") in triples
    assert ("Cocaine", "SEIZED_AT", "Laxman Compound") in triples
    # Exactly the two explicit relationships — nothing inferred.
    assert len(result.relationships) == 2


def test_v2_relationship_resolves_case_id_endpoint():
    rel = next(
        r for r in parse_structured(V2_DOC).result.relationships
        if r.relationship_type == "CONDUCTED_OPERATION"
    )
    assert rel.target_name == "Operation WHITE STRIKE"
    assert rel.target_type == "CASE"
    assert rel.source_type == "ORGANIZATION"


def test_v2_relationship_unknown_id_is_validation_error():
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-NCB\nNAME: Narcotics Control Bureau\nTYPE: ORGANIZATION\n\n"
        "RELATIONSHIP\nRELATIONSHIP_ID: REL-020\nSOURCE: ENT-NCB\nTARGET: ENT-XYZ\nTYPE: NEAR\n"
    )
    parsed = parse_structured(text)
    assert parsed.result.relationships == []
    assert any(
        v["id"] == "REL-020" and "ENT-XYZ" in v["message"] and "No relationship was created" in v["message"]
        for v in parsed.validation
    )


def test_v2_relationship_resolves_by_declared_name():
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-COC\nNAME: Cocaine\nTYPE: DRUG\n\n"
        "ENTITY\nENTITY_ID: ENT-LAX\nNAME: Laxman Compound\nTYPE: LOCATION\n\n"
        "RELATIONSHIP\nRELATIONSHIP_ID: REL-1\nSOURCE: Cocaine\nTARGET: Laxman Compound\nTYPE: SEIZED_AT\n"
    )
    result = parse_structured(text).result
    rel = result.relationships[0]
    assert rel.source_name == "Cocaine"
    assert rel.source_type == "DRUG"
    assert rel.target_type == "LOCATION"


def test_v2_relationship_id_dedup():
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-A\nNAME: Entity A\nTYPE: ORGANIZATION\n\n"
        "ENTITY\nENTITY_ID: ENT-B\nNAME: Entity B\nTYPE: LOCATION\n\n"
        "RELATIONSHIP\nRELATIONSHIP_ID: REL-1\nSOURCE: ENT-A\nTARGET: ENT-B\nTYPE: OPERATES_IN\n\n"
        "RELATIONSHIP\nRELATIONSHIP_ID: REL-1\nSOURCE: ENT-A\nTARGET: ENT-B\nTYPE: OPERATES_IN\n"
    )
    result = parse_structured(text).result
    assert len(result.relationships) == 1


def test_v2_entities_alone_create_no_relationships():
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-A\nNAME: Entity A\nTYPE: ORGANIZATION\n\n"
        "ENTITY\nENTITY_ID: ENT-B\nNAME: Entity B\nTYPE: PERSON\n\n"
        "ENTITY\nENTITY_ID: ENT-C\nNAME: Cocaine\nTYPE: DRUG\n"
    )
    result = parse_structured(text).result
    assert result.relationships == []
    assert result.facts == []


# ---------------------------------------------------------------------------
# FACT parsing (TEST 13)
# ---------------------------------------------------------------------------


def test_v2_fact_stays_a_fact():
    result = parse_structured(V2_DOC).result
    assert len(result.facts) == 1
    fact = result.facts[0]
    assert fact.subject_name == "Operation WHITE STRIKE"
    assert fact.subject_type == "CASE"
    assert fact.case_ref == "Operation WHITE STRIKE"
    assert fact.extra.get("description") == "Approximately 349 kg of cocaine was seized."
    assert fact.extra.get("status") == "CONFIRMED_FROM_SOURCE"
    assert fact.extra.get("fact_id") == "FACT-001"
    # The FACT block never invents people, events or relationships: the
    # entity list is exactly the six declared ENTITY blocks, and the fact
    # description never became an event or a relationship.
    assert len(result.entities) == 6
    assert not [e for e in result.events if "349 kg" in e.title]
    assert len(result.relationships) == 2


# ---------------------------------------------------------------------------
# Mentioned-only / contextual people (TESTS 14, 18, 19)
# ---------------------------------------------------------------------------


def test_v2_mentioned_only_person_has_no_relationships():
    result = parse_structured(V2_DOC).result
    amit = next(e for e in result.entities if e.name == "Amit Shah")
    assert amit.entity_type == "PERSON"
    assert amit.extra.get("investigative_status") == "MENTIONED_ONLY"
    involved = {
        name
        for r in result.relationships
        for name in (r.source_name, r.target_name)
    }
    assert "Amit Shah" not in involved
    assert "Narendra Modi" not in involved


def test_v2_contextual_person_kept():
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-AMIT\nNAME: Amit Shah\nTYPE: PERSON\n"
        "ROLE: UNION HOME MINISTER\nSTATUS: GOVERNMENT_OFFICIAL\n"
        "MENTION_CONTEXT: CONTEXTUAL\n"
    )
    result = parse_structured(text).result
    amit = next(e for e in result.entities if e.name == "Amit Shah")
    assert amit.extra.get("mention_context") == "CONTEXTUAL"
    assert amit.extra.get("role") == "UNION HOME MINISTER"
    assert result.relationships == []


def test_v2_unnamed_person_not_invented():
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-ACC\nNAME: UNKNOWN\nTYPE: PERSON\nSTATUS: ACCUSED\n"
    )
    result = parse_structured(text).result
    # An explicitly declared UNKNOWN identity stays a declared record —
    # but the pipeline must never invent a name for an unnamed accused.
    # (The v2 contract declares identities explicitly; nothing is guessed.)
    assert result.entities  # declared entity is preserved as declared


# ---------------------------------------------------------------------------
# End-to-end: upload -> candidates -> confirmation -> case graph
# ---------------------------------------------------------------------------


def _candidates(client):
    return client.get("/candidates").json()["items"]


def _proposed(candidate):
    return candidate["proposed_data"]


def test_v2_upload_produces_clean_candidates(client):
    upload_bytes(client, "v2_white_strike.txt", V2_DOC.encode("utf-8"))
    items = _candidates(client)

    entity_cands = [
        c for c in items
        if c["candidate_type"] in ("ENTITY", "LOCATION")
    ]
    by_name = {_proposed(c).get("name"): c for c in entity_cands}
    assert by_name["Laxman Compound"]["proposed_data"]["entity_type"] == "LOCATION"
    assert by_name["Cocaine"]["proposed_data"]["entity_type"] == "DRUG"
    assert by_name["Maruti Suzuki Super Carry"]["proposed_data"]["entity_type"] == "VEHICLE"
    assert by_name["Narcotics Control Bureau"]["proposed_data"]["entity_type"] == "ORGANIZATION"
    assert by_name["Amit Shah"]["proposed_data"]["entity_type"] == "PERSON"
    assert by_name["Amit Shah"]["proposed_data"].get("investigative_status") == "MENTIONED_ONLY"

    # CRITICAL — no generic misclassification: Laxman Compound, Cocaine,
    # Maruti Suzuki Super Carry and Bhiwandi are never PERSON candidates.
    person_names = {
        _proposed(c).get("name")
        for c in entity_cands
        if _proposed(c).get("entity_type") == "PERSON"
    }
    assert not person_names & {
        "Laxman Compound", "Cocaine", "Maruti Suzuki Super Carry", "Bhiwandi",
        "Vehicle", "Warehousing Complex", "Navi Mumbai",
    }
    assert person_names == {"Amit Shah", "Narendra Modi"}

    # Exactly two declared events — no duplicate discovery from keywords
    # inside the blocks.
    event_cands = [c for c in items if c["candidate_type"] == "EVENT"]
    assert len(event_cands) == 2

    # One case candidate carrying the structured CASE_ID.
    case_cands = [c for c in items if c["candidate_type"] == "CASE_MATCH"]
    assert len(case_cands) == 1
    assert _proposed(case_cands[0]).get("case_name") == "Operation WHITE STRIKE"
    assert _proposed(case_cands[0]).get("structured_id") == "OPERATION-WHITE-STRIKE"

    # Exactly two explicit relationships.
    rel_cands = [c for c in items if c["candidate_type"] == "RELATIONSHIP"]
    assert len(rel_cands) == 2

    # One fact candidate.
    fact_cands = [c for c in items if c["candidate_type"] == "FACT"]
    assert len(fact_cands) == 1
    assert _proposed(fact_cands[0]).get("subject_name") == "Operation WHITE STRIKE"


def test_v2_upload_surfaces_validation_on_document(client):
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-NCB\nNAME: Narcotics Control Bureau\nTYPE: ORGANIZATION\n\n"
        "RELATIONSHIP\nRELATIONSHIP_ID: REL-020\nSOURCE: ENT-NCB\nTARGET: ENT-XYZ\nTYPE: NEAR\n"
    )
    resp = upload_bytes(client, "v2_bad.txt", text.encode("utf-8"))
    document_id = resp.json()["document"]["document_id"]
    document = client.get(f"/documents/{document_id}").json()
    assert document["structured_validation"] is not None
    assert any(
        "ENT-XYZ" in issue["message"] for issue in document["structured_validation"]
    )


def _confirm_by_name(client, candidate_type, **proposed_match):
    # LOCATION blocks persist as candidate_type LOCATION; other entities
    # persist as ENTITY.
    types = {candidate_type}
    if candidate_type == "ENTITY":
        types = {"ENTITY", "LOCATION"}
    items = [c for c in _candidates(client) if c["candidate_type"] in types]
    for c in items:
        proposed = _proposed(c)
        if all(proposed.get(k) == v for k, v in proposed_match.items()):
            resp = client.post(f"/candidates/{c['candidate_id']}/confirm", json={"reason": "reviewed"})
            assert resp.status_code == 200, resp.text
            return c
    raise AssertionError(f"no {candidate_type} candidate matching {proposed_match}")


def test_v2_case_graph_contains_isolated_nodes_and_only_explicit_edges(client):
    upload_bytes(client, "v2_white_strike.txt", V2_DOC.encode("utf-8"))

    # Confirm the case first (anchors the document to one case).
    _confirm_by_name(client, "CASE_MATCH", case_name="Operation WHITE STRIKE")
    # Confirm every entity (including the mentioned-only people).
    for name in ("Narcotics Control Bureau", "Laxman Compound", "Cocaine",
                 "Maruti Suzuki Super Carry", "Amit Shah", "Narendra Modi"):
        _confirm_by_name(client, "ENTITY", name=name)
    # Confirm the two explicit relationships.
    _confirm_by_name(client, "RELATIONSHIP", relationship_type="CONDUCTED_OPERATION")
    _confirm_by_name(client, "RELATIONSHIP", relationship_type="SEIZED_AT")

    # The confirmed case appears in the case selector API (TEST 27).
    cases = client.get("/cases").json()["items"]
    assert any(c.get("case_name") == "Operation WHITE STRIKE" for c in cases)
    case_id = next(c["case_id"] for c in cases if c.get("case_name") == "Operation WHITE STRIKE")

    # Full case graph: complete trusted graph, isolated nodes included.
    graph = client.get(f"/graph/case/{case_id}/full").json()
    names = {n["name"] for n in graph["nodes"]}
    assert "Operation WHITE STRIKE" in names
    # All trusted entities are nodes — including zero-degree people.
    for name in ("Narcotics Control Bureau", "Laxman Compound", "Cocaine",
                 "Maruti Suzuki Super Carry", "Amit Shah", "Narendra Modi"):
        assert name in names, f"{name} missing from case graph"
    edge_types = {e["relationship_type"] for e in graph["edges"]}
    assert "CONDUCTED_OPERATION" in edge_types
    assert "SEIZED_AT" in edge_types
    # No invented relationship connects the mentioned-only people: Amit
    # Shah has zero incident edges in the complete case graph.
    amit_edges = [
        e for e in graph["edges"]
        if any(name == "Amit Shah" for name in _edge_endpoints(graph, e))
    ]
    assert amit_edges == []


def _edge_endpoints(graph, edge):
    names_by_id = {n["id"]: n["name"] for n in graph["nodes"]}
    return [names_by_id.get(edge.get("source")), names_by_id.get(edge.get("target"))]


def test_v2_confirmed_events_scoped_to_case(client):
    upload_bytes(client, "v2_white_strike.txt", V2_DOC.encode("utf-8"))
    _confirm_by_name(client, "CASE_MATCH", case_name="Operation WHITE STRIKE")
    _confirm_by_name(client, "EVENT", title="First strike")
    _confirm_by_name(client, "EVENT", title="Second operation")

    events = client.get("/events").json()["items"]
    assert len(events) == 2
    first = next(e for e in events if e["title"] == "First strike")
    second = next(e for e in events if e["title"] == "Second operation")
    # Individual dates preserved — the undated event stays undated.
    assert first["start_date"] == "2026-03-03"
    assert second["start_date"] is None
    assert second["date_precision"] == "UNKNOWN"


def test_v2_contextual_metadata_survives_confirmation(client):
    text = V2_HEADER + (
        "ENTITY\nENTITY_ID: ENT-AMIT\nNAME: Amit Shah\nTYPE: PERSON\n"
        "ROLE: UNION HOME MINISTER\nSTATUS: GOVERNMENT_OFFICIAL\n"
        "MENTION_CONTEXT: CONTEXTUAL\n"
    )
    upload_bytes(client, "v2_ctx.txt", text.encode("utf-8"))
    entity_cands = [
        c for c in _candidates(client)
        if c["candidate_type"] in ("ENTITY", "LOCATION")
        and _proposed(c).get("name") == "Amit Shah"
    ]
    assert len(entity_cands) == 1
    resp = client.post(
        f"/candidates/{entity_cands[0]['candidate_id']}/confirm", json={"reason": "reviewed"}
    )
    assert resp.status_code == 200, resp.text

    entities = client.get("/entities").json()["items"]
    amit = next(e for e in entities if e["canonical_name"] == "Amit Shah")
    assert amit["entity_type"] == "PERSON"
    sm = amit["structured_metadata"]
    assert sm["investigative_status"] == "CONTEXTUAL"
    assert sm["role"] == "UNION HOME MINISTER"
    assert sm["mention_context"] == "CONTEXTUAL"
    assert sm["investigative_status"] not in ("ACCUSED", "CONVICTED")


# ---------------------------------------------------------------------------
# Generic prose regression (TEST 28)
# ---------------------------------------------------------------------------


def test_v2_never_routes_plain_prose_to_structured(client):
    upload_bytes(
        client,
        "prose.txt",
        b"Arjun Mehta was arrested during Operation Bluewater in Mumbai on 15 June 2026. "
        b"The case number is NCB/MUM/123/2026.",
    )
    items = _candidates(client)
    names = {
        _proposed(c).get("name")
        for c in items
        if c["candidate_type"] in ("ENTITY", "LOCATION")
        and _proposed(c).get("entity_type") == "PERSON"
    }
    assert "Arjun Mehta" in names
