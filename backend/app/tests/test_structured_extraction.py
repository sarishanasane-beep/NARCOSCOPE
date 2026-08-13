"""STRUCTURED TXT PARSING TESTS.

The structured parser reads labelled sections (``PERSON:``, ``DRUG:``,
``RELATIONSHIP:`` ...) as EXPLICIT semantic instructions. These tests
verify that:

- every declared entity keeps its declared type (Cocaine is DRUG, never
  PERSON; Mumbai is LOCATION; Maruti Suzuki Super Carry is VEHICLE),
- ARRESTED_BY is only proposed when an explicit arresting organization
  is present in the ARREST block,
- CONVICTED is only proposed from an explicit CONVICTION block,
- CASE blocks never create a duplicate OTHER entity unless a graph
  relationship genuinely requires the endpoint,
- relationships come only from the explicit RELATIONSHIP section,
- malformed blocks are skipped safely,
- the generic engine path is untouched (plain prose is not structured).
"""

from app.services.extraction.structured import detect_structured, parse_structured
from app.tests.conftest import upload_bytes

MINIMAL_DOC = """\
DOCUMENT:
TITLE: Operation WHITE STRIKE
DATE: 01 May 2026
SOURCE: Narcotics Control Bureau

CASE:
NAME: Operation WHITE STRIKE
TYPE: DRUG_TRAFFICKING_INVESTIGATION

PERSON:
NAME: Person A
ROLE: ACCUSED
STATUS: ARRESTED

ORGANIZATION:
NAME: Narcotics Control Bureau
ROLE: INVESTIGATING_AGENCY

LOCATION:
NAME: Mumbai
TYPE: CITY

DRUG:
NAME: Cocaine
QUANTITY: 349 kg

VEHICLE:
NAME: Maruti Suzuki Super Carry
REGISTRATION: MH-03-DV-3803

EVENT:
TYPE: DRUG_SEIZURE
DESCRIPTION: NCB seized approximately 349 kg of cocaine.

ARREST:
PERSON: Person A
ARRESTED_BY_ORGANIZATION: Narcotics Control Bureau
LOCATION: Mumbai

RELATIONSHIP:
SOURCE: Narcotics Control Bureau
RELATION: ARRESTED
TARGET: Person A

RELATIONSHIP:
SOURCE: Person A
RELATION: INVOLVED_IN
TARGET: Operation WHITE STRIKE

RELATIONSHIP:
SOURCE: Operation WHITE STRIKE
RELATION: OCCURRED_AT
TARGET: Mumbai

RELATIONSHIP:
SOURCE: Operation WHITE STRIKE
RELATION: INVOLVED_DRUG
TARGET: Cocaine
"""


def _entity_names(result, entity_type: str) -> set[str]:
    return {e.name for e in result.entities if e.entity_type == entity_type}


def _rel_triples(result) -> set[tuple[str, str, str]]:
    return {
        (r.source_name, r.relationship_type, r.target_name)
        for r in result.relationships
    }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_structured_true():
    assert detect_structured(MINIMAL_DOC) is True


def test_detect_structured_false_for_prose():
    prose = (
        "PERSON: John was arrested today. The police raided the warehouse. "
        "DRUG and ORGANIZATION are words that appear in this sentence."
    )
    assert detect_structured(prose) is False


def test_detect_structured_false_for_plain_sentence():
    assert detect_structured("Arjun Mehta was arrested during Operation Bluewater.") is False


def test_detect_structured_single_header_with_field():
    text = "CASE:\nNAME: Operation Bluewater\n"
    assert detect_structured(text) is True


def test_detect_structured_single_header_alone():
    assert detect_structured("PERSON:") is False


# ---------------------------------------------------------------------------
# Section typing (tests 1, 3, 4, 5, 6, 11)
# ---------------------------------------------------------------------------


def test_person_section():
    result = parse_structured("PERSON:\nNAME: Amit Shah\n").result
    assert ("PERSON", "Amit Shah") in {(e.entity_type, e.name) for e in result.entities}
    assert "Amit Shah" not in _entity_names(result, "ORGANIZATION")
    assert "Amit Shah" not in _entity_names(result, "LOCATION")
    assert "Amit Shah" not in _entity_names(result, "DRUG")


def test_organization_section():
    result = parse_structured("ORGANIZATION:\nNAME: Narcotics Control Bureau\n").result
    assert "Narcotics Control Bureau" in _entity_names(result, "ORGANIZATION")
    assert "Narcotics Control Bureau" not in _entity_names(result, "PERSON")


def test_location_section():
    result = parse_structured("LOCATION:\nNAME: Mumbai\nTYPE: CITY\n").result
    mumbai = next(e for e in result.entities if e.name == "Mumbai")
    assert mumbai.entity_type == "LOCATION"
    assert mumbai.extra.get("location_type") == "CITY"


def test_drug_section_not_person():
    result = parse_structured("DRUG:\nNAME: Cocaine\nQUANTITY: 349 kg\n").result
    cocaine = next(e for e in result.entities if e.name == "Cocaine")
    assert cocaine.entity_type == "DRUG"
    assert cocaine.extra.get("quantity") == "349 kg"
    assert "Cocaine" not in _entity_names(result, "PERSON")


def test_vehicle_section_not_person():
    result = parse_structured(
        "VEHICLE:\nNAME: Maruti Suzuki Super Carry\nREGISTRATION: MH-03-DV-3803\n"
    ).result
    vehicle = next(e for e in result.entities if e.name == "Maruti Suzuki Super Carry")
    assert vehicle.entity_type == "VEHICLE"
    assert vehicle.extra.get("registration") == "MH-03-DV-3803"
    assert "Maruti Suzuki Super Carry" not in _entity_names(result, "PERSON")


def test_multiple_entities_keep_types():
    text = (
        "PERSON:\nNAME: John Doe\n\n"
        "ORGANIZATION:\nNAME: Narcotics Control Bureau\n\n"
        "LOCATION:\nNAME: Mumbai\n\n"
        "DRUG:\nNAME: Cocaine\n\n"
        "VEHICLE:\nNAME: Maruti Suzuki Super Carry\n"
    )
    result = parse_structured(text).result
    assert _entity_names(result, "PERSON") == {"John Doe"}
    assert _entity_names(result, "ORGANIZATION") == {"Narcotics Control Bureau"}
    assert _entity_names(result, "LOCATION") == {"Mumbai"}
    assert _entity_names(result, "DRUG") == {"Cocaine"}
    assert _entity_names(result, "VEHICLE") == {"Maruti Suzuki Super Carry"}
    assert not _entity_names(result, "PERSON") & {"Cocaine", "Mumbai", "Maruti Suzuki Super Carry"}


# ---------------------------------------------------------------------------
# Role / status (test 2) — no inference
# ---------------------------------------------------------------------------


def test_person_role_status_preserved():
    text = "PERSON:\nNAME: John Doe\nROLE: ACCUSED\nSTATUS: ARRESTED\n"
    result = parse_structured(text).result
    person = next(e for e in result.entities if e.name == "John Doe")
    assert person.extra.get("role") == "ACCUSED"
    assert person.extra.get("status") == "ARRESTED"
    # ARRESTED must never become CONVICTED.
    assert not [f for f in result.facts if f.predicate == "CONVICTED"]
    assert result.relationships == []


def test_person_without_role_is_not_criminal():
    result = parse_structured("PERSON:\nNAME: Amit Shah\n").result
    person = next(e for e in result.entities if e.name == "Amit Shah")
    assert person.extra.get("role") is None
    assert person.extra.get("status") is None


# ---------------------------------------------------------------------------
# ARREST (test 7) — ARRESTED_BY only with an explicit arresting party
# ---------------------------------------------------------------------------


def test_arrest_block_with_explicit_arresting_org():
    text = (
        "ARREST:\nPERSON: John Doe\n"
        "ARRESTED_BY_ORGANIZATION: Narcotics Control Bureau\n"
        "LOCATION: Mumbai\nDATE: 01 May 2026\n"
    )
    result = parse_structured(text).result
    assert ("John Doe", "ARRESTED_BY", "Narcotics Control Bureau") in _rel_triples(result)
    arrest = next(e for e in result.events if e.event_type == "ARREST")
    assert arrest.title == "Arrest of John Doe"
    assert arrest.location_name == "Mumbai"
    assert arrest.date is not None
    assert arrest.date.precision == "DAY"


def test_arrest_block_without_arresting_org_creates_no_relationship():
    text = "ARREST:\nPERSON: John Doe\nLOCATION: Mumbai\n"
    result = parse_structured(text).result
    assert _rel_triples(result) == set()
    # The arrest event itself is still preserved.
    assert any(e.event_type == "ARREST" for e in result.events)


def test_arrest_without_person_is_skipped():
    result = parse_structured("ARREST:\nLOCATION: Mumbai\n").result
    assert result.events == []
    assert result.relationships == []


# ---------------------------------------------------------------------------
# CONVICTION (test 8) — only when explicit
# ---------------------------------------------------------------------------


def test_conviction_only_when_explicit():
    text = (
        "PERSON:\nNAME: John Doe\nSTATUS: ARRESTED\n\n"
        "CONVICTION:\nPERSON: John Doe\nSTATUS: CONVICTED\n"
        "SENTENCE: 10 years\nCOURT: Special Court, Mumbai\n"
    )
    result = parse_structured(text).result
    conviction = next(f for f in result.facts if f.subject_name == "John Doe")
    assert conviction.predicate == "CONVICTED"
    assert conviction.extra.get("sentence") == "10 years"
    assert conviction.extra.get("court") == "Special Court, Mumbai"
    assert conviction.extra.get("status") == "CONVICTED"


def test_no_conviction_from_arrest():
    result = parse_structured(
        "PERSON:\nNAME: John Doe\nROLE: ACCUSED\nSTATUS: ARRESTED\n"
    ).result
    assert not [f for f in result.facts if f.predicate == "CONVICTED"]


def test_conviction_without_person_is_skipped():
    result = parse_structured("CONVICTION:\nSTATUS: CONVICTED\nSENTENCE: 10 years\n").result
    assert result.facts == []


# ---------------------------------------------------------------------------
# SEIZURE — preserved as an event, quantities never become entities
# ---------------------------------------------------------------------------


def test_seizure_section_creates_event_with_quantity_value():
    text = (
        "SEIZURE:\nDRUG: Cocaine\nQUANTITY: 349 kg\n"
        "VALUE: INR 1,745 crore\nLOCATION: Mumbai\n"
    )
    result = parse_structured(text).result
    seizure = next(e for e in result.events if e.event_type == "SEIZURE")
    assert seizure.title == "Seizure of Cocaine"
    assert seizure.extra.get("quantity") == "349 kg"
    assert seizure.extra.get("value") == "INR 1,745 crore"
    assert seizure.location_name == "Mumbai"
    # Quantities and values never become entities.
    assert result.entities == []
    assert result.relationships == []


# ---------------------------------------------------------------------------
# RELATIONSHIP (tests 9, 10) — explicit only, no inventions
# ---------------------------------------------------------------------------


def test_relationship_section_mapping():
    text = (
        "PERSON:\nNAME: John Doe\n\n"
        "ORGANIZATION:\nNAME: Narcotics Control Bureau\n\n"
        "RELATIONSHIP:\nSOURCE: Narcotics Control Bureau\n"
        "RELATION: ARRESTED\nTARGET: John Doe\n"
    )
    result = parse_structured(text).result
    rel = next(r for r in result.relationships)
    assert rel.source_name == "Narcotics Control Bureau"
    assert rel.relationship_type == "ARRESTED"
    assert rel.target_name == "John Doe"
    assert rel.source_type == "ORGANIZATION"
    assert rel.target_type == "PERSON"


def test_relationship_type_field_name_variants():
    """RELATIONSHIP_TYPE / RELATION / TYPE are all accepted field names."""
    for field_name in ("RELATIONSHIP_TYPE", "RELATION", "TYPE"):
        text = (
            "PERSON:\nNAME: John Doe\n\n"
            "ORGANIZATION:\nNAME: Narcotics Control Bureau\n\n"
            f"RELATIONSHIP:\nSOURCE: Narcotics Control Bureau\n{field_name}: ARRESTED\nTARGET: John Doe\n"
        )
        result = parse_structured(text).result
        rels = [r for r in result.relationships if r.relationship_type == "ARRESTED"]
        assert len(rels) == 1, f"field {field_name} produced {len(rels)} relationships"


def test_duplicate_relationship_declarations_dedupe():
    text = (
        "ORGANIZATION:\nNAME: Narcotics Control Bureau\n\n"
        "PERSON:\nNAME: John Doe\n\n"
        "RELATIONSHIP:\nSOURCE: Narcotics Control Bureau\nRELATIONSHIP_TYPE: ARRESTED\nTARGET: John Doe\n\n"
        "RELATIONSHIP:\nSOURCE: Narcotics Control Bureau\nRELATIONSHIP_TYPE: ARRESTED\nTARGET: John Doe\n"
    )
    result = parse_structured(text).result
    assert len(result.relationships) == 1


def test_drug_section_alone_creates_no_relationship():
    result = parse_structured("DRUG:\nNAME: Cocaine\nQUANTITY: 349 kg\n").result
    assert result.relationships == []
    assert not [f for f in result.facts]


def test_no_invented_drug_person_relationship():
    text = (
        "DRUG:\nNAME: Cocaine\n\n"
        "PERSON:\nNAME: John Doe\n\n"
        "RELATIONSHIP:\nSOURCE: John Doe\nRELATION: INVOLVED_IN\nTARGET: Operation WHITE STRIKE\n"
    )
    result = parse_structured(text).result
    triples = _rel_triples(result)
    # Exactly the one explicit relationship — Cocaine is not linked to John
    # Doe as a person.
    assert triples == {("John Doe", "INVOLVED_IN", "Operation WHITE STRIKE")}
    assert "Cocaine" in _entity_names(result, "DRUG")


# ---------------------------------------------------------------------------
# CASE handling — no duplicate OTHER entity unless a graph edge needs it
# ---------------------------------------------------------------------------


def test_case_block_creates_no_duplicate_entity():
    result = parse_structured("CASE:\nNAME: Operation Bluewater\nTYPE: DRUG_TRAFFICKING_INVESTIGATION\n").result
    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.case_name == "Operation Bluewater"
    assert case.category == "DRUG_TRAFFICKING_INVESTIGATION"
    assert case.action == "create"
    assert result.entities == []


def test_case_entity_created_only_when_relationship_requires():
    text = (
        "CASE:\nNAME: Operation Bluewater\n\n"
        "PERSON:\nNAME: John Doe\n\n"
        "RELATIONSHIP:\nSOURCE: John Doe\nRELATION: INVOLVED_IN\nTARGET: Operation Bluewater\n"
    )
    result = parse_structured(text).result
    assert len(result.cases) == 1
    # The endpoint entity carries entity_type CASE — never a generic OTHER.
    assert "Operation Bluewater" in _entity_names(result, "CASE")
    assert "Operation Bluewater" not in _entity_names(result, "OTHER")
    assert ("John Doe", "INVOLVED_IN", "Operation Bluewater") in _rel_triples(result)


# ---------------------------------------------------------------------------
# Malformed input / deduplication
# ---------------------------------------------------------------------------


def test_malformed_blocks_are_skipped_safely():
    text = (
        "PERSON:\nNAME:\n\n"  # empty name — skipped
        "ORGANIZATION:\nNAME: Narcotics Control Bureau\n\n"
        "RELATIONSHIP:\nSOURCE: A\nRELATION: ARRESTED\n"  # missing TARGET — skipped
    )
    result = parse_structured(text).result
    assert _entity_names(result, "ORGANIZATION") == {"Narcotics Control Bureau"}
    assert not [e for e in result.entities if e.name == ""]
    assert result.relationships == []


def test_duplicate_person_blocks_dedupe():
    text = (
        "PERSON:\nNAME: John Doe\n\n"
        "PERSON:\nNAME: John Doe\nROLE: ACCUSED\n"
    )
    result = parse_structured(text).result
    persons = [e for e in result.entities if e.entity_type == "PERSON"]
    assert len(persons) == 1
    assert persons[0].extra.get("role") == "ACCUSED"
    assert len(persons[0].extra.get("occurrence_spans") or []) == 2


# ---------------------------------------------------------------------------
# Evidence / spans
# ---------------------------------------------------------------------------


def test_evidence_span_is_the_block_text():
    text = "DRUG:\nNAME: Cocaine\nQUANTITY: 349 kg\n"
    result = parse_structured(text).result
    cocaine = next(e for e in result.entities if e.name == "Cocaine")
    assert "NAME: Cocaine" in cocaine.span.text
    assert "QUANTITY: 349 kg" in cocaine.span.text
    # The span must resolve back into the original document text.
    assert text[cocaine.span.start : cocaine.span.end] == cocaine.span.text


# ---------------------------------------------------------------------------
# Integration: upload the minimal real-world document
# ---------------------------------------------------------------------------


def _candidates(client):
    return client.get("/candidates").json()["items"]


def _proposed(candidate):
    return candidate["proposed_data"]


def _entity_candidates(client):
    return [
        c for c in _candidates(client)
        if c["candidate_type"] in ("ENTITY", "LOCATION")
    ]


def test_upload_structured_document_end_to_end(client):
    upload_bytes(client, "white_strike.txt", MINIMAL_DOC.encode("utf-8"))

    items = _candidates(client)
    entities = _entity_candidates(client)
    by_name = {_proposed(c).get("name"): c for c in entities}

    # Declared types (tests 1–6 at the pipeline level).
    assert by_name["Person A"]["proposed_data"]["entity_type"] == "PERSON"
    assert by_name["Person A"]["proposed_data"].get("role") == "ACCUSED"
    assert by_name["Person A"]["proposed_data"].get("status") == "ARRESTED"
    assert by_name["Narcotics Control Bureau"]["proposed_data"]["entity_type"] == "ORGANIZATION"
    assert by_name["Mumbai"]["proposed_data"]["entity_type"] == "LOCATION"
    assert by_name["Cocaine"]["proposed_data"]["entity_type"] == "DRUG"
    assert by_name["Cocaine"]["proposed_data"].get("quantity") == "349 kg"
    assert by_name["Maruti Suzuki Super Carry"]["proposed_data"]["entity_type"] == "VEHICLE"
    assert by_name["Maruti Suzuki Super Carry"]["proposed_data"].get("registration") == "MH-03-DV-3803"

    # CRITICAL: Cocaine, Mumbai and Maruti Suzuki Super Carry are NOT people.
    person_names = {
        _proposed(c).get("name")
        for c in entities
        if _proposed(c).get("entity_type") == "PERSON"
    }
    assert "Cocaine" not in person_names
    assert "Mumbai" not in person_names
    assert "Maruti Suzuki Super Carry" not in person_names

    # The operation is a CASE (no entity for the case itself unless a
    # relationship references it — which it does here, so the endpoint
    # entity exists for the graph edge).
    case_matches = [c for c in items if c["candidate_type"] == "CASE_MATCH"]
    assert any(
        _proposed(c).get("case_name") == "Operation WHITE STRIKE"
        and _proposed(c).get("category") == "DRUG_TRAFFICKING_INVESTIGATION"
        for c in case_matches
    )
    assert by_name["Operation WHITE STRIKE"]["proposed_data"]["entity_type"] == "CASE"

    # Relationships: exactly the five explicit ones — nothing invented.
    rels = [c for c in items if c["candidate_type"] == "RELATIONSHIP"]
    triples = {
        (
            _proposed(r).get("source_name"),
            _proposed(r).get("relationship_type"),
            _proposed(r).get("target_name"),
        )
        for r in rels
    }
    assert triples == {
        ("Narcotics Control Bureau", "ARRESTED", "Person A"),
        ("Person A", "INVOLVED_IN", "Operation WHITE STRIKE"),
        ("Operation WHITE STRIKE", "OCCURRED_AT", "Mumbai"),
        ("Operation WHITE STRIKE", "INVOLVED_DRUG", "Cocaine"),
        ("Person A", "ARRESTED_BY", "Narcotics Control Bureau"),
    }

    # Events: the explicit ARREST + the explicit DRUG_SEIZURE event.
    events = [c for c in items if c["candidate_type"] == "EVENT"]
    event_titles = {_proposed(e).get("title") for e in events}
    assert "Arrest of Person A" in event_titles
    assert "NCB seized approximately 349 kg of cocaine." in event_titles
    arrest = next(e for e in events if _proposed(e).get("title") == "Arrest of Person A")
    # The ARREST block carries no DATE — no date is invented (the DOCUMENT
    # date is the publication date, not the arrest date).
    assert _proposed(arrest).get("start_date") is None
    assert _proposed(arrest).get("location_name") == "Mumbai"

    # Evidence: every candidate traces back to the exact block text.
    cocaine = by_name["Cocaine"]
    refs = cocaine.get("evidence_refs") or []
    assert any("Cocaine" in r["exact_text"] for r in refs)

    # No unsupported conviction was invented.
    assert not [f for f in items if _proposed(f).get("predicate") == "CONVICTED"]


def test_upload_structured_document_metadata(client):
    text = (
        "DOCUMENT:\nTITLE: Operation WHITE STRIKE\nDATE: 01 May 2026\n"
        "SOURCE: Narcotics Control Bureau\nSOURCE_TYPE: GOVERNMENT_PRESS_RELEASE\n\n"
        "CASE:\nNAME: Operation WHITE STRIKE\n"
    )
    resp = upload_bytes(client, "meta.txt", text.encode("utf-8"))
    document_id = resp.json()["document"]["document_id"]
    document = client.get(f"/documents/{document_id}").json()
    assert document["publication_date"] == "2026-05-01"
    assert document["source_id"] is not None

    sources = client.get("/sources").json()["items"]
    source = next(s for s in sources if s["source_id"] == document["source_id"])
    assert source["publisher"] == "Narcotics Control Bureau"
    assert source["source_type"] == "GOVERNMENT_PRESS_RELEASE"
    assert source["publication_date"] == "2026-05-01"


RELATIONSHIP_DOC = (
    "ORGANIZATION:\nNAME: Narcotics Control Bureau\n\n"
    "PERSON:\nNAME: John Doe\n\n"
    "RELATIONSHIP:\nSOURCE: Narcotics Control Bureau\n"
    "RELATIONSHIP_TYPE: ARRESTED\nTARGET: John Doe\n"
)


def _relationship_candidates(client):
    return client.get("/candidates?candidate_type=RELATIONSHIP").json()["items"]


def test_relationship_candidates_created_pending_with_evidence(client):
    """TEST 2/3/4/5 — persist_extraction creates PENDING relationship
    candidates that the Candidate Review API returns with evidence."""
    upload_bytes(client, "rel.txt", RELATIONSHIP_DOC.encode("utf-8"))
    rels = _relationship_candidates(client)
    assert len(rels) == 1
    rel = rels[0]
    assert rel["status"] == "PENDING"
    proposed = rel["proposed_data"]
    assert proposed["source_name"] == "Narcotics Control Bureau"
    assert proposed["source_type"] == "ORGANIZATION"
    assert proposed["relationship_type"] == "ARRESTED"
    assert proposed["target_name"] == "John Doe"
    assert proposed["target_type"] == "PERSON"
    refs = rel.get("evidence_refs") or []
    assert any("RELATIONSHIP" in r["exact_text"] for r in refs)


def test_confirm_relationship_creates_trusted_edge(client):
    """TEST 6/7/8 — confirming a relationship candidate creates the trusted
    relationship record and a graph edge."""
    upload_bytes(client, "rel.txt", RELATIONSHIP_DOC.encode("utf-8"))
    rel = _relationship_candidates(client)[0]
    resp = client.post(f"/candidates/{rel['candidate_id']}/confirm", json={"reason": "reviewed"})
    assert resp.status_code == 200, resp.text

    trusted = client.get("/relationships").json()["items"]
    assert len(trusted) == 1
    assert trusted[0]["relationship_type"] == "ARRESTED"
    assert trusted[0]["status"] == "CONFIRMED"

    stats = client.get("/graph/stats").json()
    assert stats["total_edges"] >= 1
    assert stats["edges_by_type"].get("ARRESTED") == 1


def test_reject_relationship_does_not_create_edge(client):
    """TEST 9 — rejecting a relationship candidate never creates a trusted edge."""
    upload_bytes(client, "rel.txt", RELATIONSHIP_DOC.encode("utf-8"))
    rel = _relationship_candidates(client)[0]
    resp = client.post(f"/candidates/{rel['candidate_id']}/reject", json={"reason": "not supported"})
    assert resp.status_code == 200, resp.text

    assert client.get("/relationships").json()["total"] == 0
    assert client.get("/graph/stats").json()["total_edges"] == 0


def test_white_strike_actual_document_full_pipeline(client):
    """End-to-end with the REAL WHITE STRIKE document: the six explicit
    RELATIONSHIP blocks must become six PENDING candidates, and confirming
    them must create the trusted edges."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "white_strike_structured.txt"
    upload_bytes(client, "white_strike_structured.txt", fixture.read_bytes())

    rels = _relationship_candidates(client)
    triples = {
        (
            _proposed(r).get("source_name"),
            _proposed(r).get("relationship_type"),
            _proposed(r).get("target_name"),
        )
        for r in rels
    }
    assert triples == {
        ("Narcotics Control Bureau", "CONDUCTED_OPERATION", "Operation WHITE STRIKE"),
        ("Operation WHITE STRIKE", "OCCURRED_AT", "Mumbai"),
        ("Operation WHITE STRIKE", "INVOLVED_DRUG", "Cocaine"),
        ("Maruti Suzuki Super Carry", "INTERCEPTED_AT", "KWC Warehousing Complex"),
        ("Cocaine", "SEIZED_AT", "KWC Warehousing Complex"),
        ("Cocaine", "SEIZED_AT", "Laxman Compound"),
    }
    assert len(rels) == 6
    assert all(r["status"] == "PENDING" for r in rels)

    # Confirm every relationship candidate.
    for rel in rels:
        resp = client.post(f"/candidates/{rel['candidate_id']}/confirm", json={"reason": "reviewed"})
        assert resp.status_code == 200, resp.text

    trusted = client.get("/relationships").json()["items"]
    assert len(trusted) == 6
    stats = client.get("/graph/stats").json()
    assert stats["total_edges"] == 6


CONTEXTUAL_PERSON_BLOCK = (
    "PERSON:\nNAME: Amit Shah\nROLE: UNION HOME MINISTER\n"
    "STATUS: GOVERNMENT_OFFICIAL\nMENTION_CONTEXT: CONTEXTUAL\n"
)


# ---------------------------------------------------------------------------
# PERSON semantics — contextual vs investigative (TESTS 1-6)
# ---------------------------------------------------------------------------


def test_amit_shah_extracted_as_person(client):
    """TEST 1 — Amit Shah is a PERSON, never another type."""
    result = parse_structured(CONTEXTUAL_PERSON_BLOCK).result
    amit = next(e for e in result.entities if e.name == "Amit Shah")
    assert amit.entity_type == "PERSON"
    assert "Amit Shah" not in _entity_names(result, "ORGANIZATION")
    assert "Amit Shah" not in _entity_names(result, "LOCATION")


def test_narendra_modi_extracted_as_person():
    """TEST 2 — Narendra Modi is a PERSON."""
    text = (
        "PERSON:\nNAME: Narendra Modi\nROLE: PRIME MINISTER\n"
        "STATUS: GOVERNMENT_OFFICIAL\nMENTION_CONTEXT: CONTEXTUAL\n"
    )
    result = parse_structured(text).result
    modi = next(e for e in result.entities if e.name == "Narendra Modi")
    assert modi.entity_type == "PERSON"


def test_amit_shah_contextual_metadata(client):
    """TEST 3 — Amit Shah is marked as a contextual government official."""
    upload_bytes(client, "ctx.txt", CONTEXTUAL_PERSON_BLOCK.encode("utf-8"))
    candidates = [
        c for c in _entity_candidates(client)
        if _proposed(c).get("name") == "Amit Shah"
    ]
    assert len(candidates) == 1
    proposed = _proposed(candidates[0])
    assert proposed["entity_type"] == "PERSON"
    assert proposed.get("role") == "UNION HOME MINISTER"
    assert proposed.get("status") == "GOVERNMENT_OFFICIAL"
    assert proposed.get("mention_context") == "CONTEXTUAL"
    # The reviewer-facing labels never imply accusation or guilt.
    assert proposed.get("role") not in ("ACCUSED", "SUSPECT", "CRIMINAL")


def test_narendra_modi_contextual_metadata(client):
    """TEST 4 — Narendra Modi is marked as a contextual government official."""
    text = (
        "PERSON:\nNAME: Narendra Modi\nROLE: PRIME MINISTER\n"
        "STATUS: GOVERNMENT_OFFICIAL\nMENTION_CONTEXT: CONTEXTUAL\n"
    )
    upload_bytes(client, "ctx2.txt", text.encode("utf-8"))
    candidates = [
        c for c in _entity_candidates(client)
        if _proposed(c).get("name") == "Narendra Modi"
    ]
    assert len(candidates) == 1
    proposed = _proposed(candidates[0])
    assert proposed.get("role") == "PRIME MINISTER"
    assert proposed.get("mention_context") == "CONTEXTUAL"


def test_contextual_people_get_no_investigative_relationships(client):
    """TESTS 5 & 6 — Amit Shah and Narendra Modi receive NO investigative
    relationships from the real WHITE STRIKE document."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "white_strike_structured.txt"
    upload_bytes(client, "white_strike_structured.txt", fixture.read_bytes())

    rels = _relationship_candidates(client)
    involved = {
        name
        for r in rels
        for name in (_proposed(r).get("source_name"), _proposed(r).get("target_name"))
        if name in ("Amit Shah", "Narendra Modi")
    }
    assert involved == set()
    # Their PERSON candidates still exist for review.
    names = {_proposed(c).get("name") for c in _entity_candidates(client)}
    assert "Amit Shah" in names
    assert "Narendra Modi" in names


# ---------------------------------------------------------------------------
# Unnamed accused (TESTS 7-8)
# ---------------------------------------------------------------------------


def test_unnamed_accused_no_fake_person():
    """TEST 7 — an arrest without a name never creates a fake PERSON."""
    text = (
        "ARREST:\nPERSON: UNKNOWN\nARRESTED_BY_ORGANIZATION: Narcotics Control Bureau\n"
        "LOCATION: Mumbai\n"
    )
    result = parse_structured(text).result
    assert not [e for e in result.entities if e.entity_type == "PERSON"]
    assert result.relationships == []
    arrest = next(e for e in result.events if e.event_type == "ARREST")
    assert arrest.extra.get("accused_identity") == "NOT_PROVIDED"


def test_arrest_event_represents_unnamed_accused(client):
    """TEST 8 — the ARREST event preserves identity as NOT_PROVIDED."""
    text = (
        "EVENT:\nTYPE: ARREST\nSTATUS: ONE_ACCUSED_APPREHENDED\n"
        "LOCATION: KWC Warehousing Complex\n"
        "DESCRIPTION: One accused was apprehended on the spot.\n"
    )
    upload_bytes(client, "arrest.txt", text.encode("utf-8"))
    events = [c for c in _candidates(client) if c["candidate_type"] == "EVENT"]
    assert len(events) == 1
    proposed = _proposed(events[0])
    assert proposed.get("event_type") == "ARREST"
    assert proposed.get("status") == "ONE_ACCUSED_APPREHENDED"
    assert proposed.get("accused_identity") == "NOT_PROVIDED"
    # No fake person is proposed.
    assert not [c for c in _entity_candidates(client) if _proposed(c).get("name") in ("Unknown", "Unnamed Accused")]


# ---------------------------------------------------------------------------
# CASE representation (TESTS 9-10)
# ---------------------------------------------------------------------------


def test_case_remains_a_case(client):
    """TEST 9 — Operation WHITE STRIKE remains a CASE record."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "white_strike_structured.txt"
    upload_bytes(client, "white_strike_structured.txt", fixture.read_bytes())
    case_matches = [c for c in _candidates(client) if c["candidate_type"] == "CASE_MATCH"]
    assert any(
        _proposed(c).get("case_name") == "Operation WHITE STRIKE"
        and _proposed(c).get("category") == "DRUG_TRAFFICKING_INVESTIGATION"
        for c in case_matches
    )


def test_no_duplicate_other_entity_for_confirmed_case(client):
    """TEST 10 — a relationship referencing the case never produces a
    duplicate OTHER entity when the CASE exists; the endpoint entity is
    CASE-typed instead."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "white_strike_structured.txt"
    upload_bytes(client, "white_strike_structured.txt", fixture.read_bytes())
    items = _candidates(client)

    case_candidate = next(
        c for c in items
        if c["candidate_type"] == "CASE_MATCH"
        and _proposed(c).get("case_name") == "Operation WHITE STRIKE"
    )
    resp = client.post(f"/candidates/{case_candidate['candidate_id']}/confirm", json={"reason": "reviewed"})
    assert resp.status_code == 200, resp.text

    rel = next(
        c for c in items
        if c["candidate_type"] == "RELATIONSHIP"
        and _proposed(c).get("relationship_type") == "CONDUCTED_OPERATION"
    )
    resp = client.post(f"/candidates/{rel['candidate_id']}/confirm", json={"reason": "reviewed"})
    assert resp.status_code == 200, resp.text

    entities = client.get("/entities").json()["items"]
    operation_entities = [e for e in entities if e["canonical_name"] == "Operation WHITE STRIKE"]
    assert operation_entities, "the case endpoint entity must exist for the graph edge"
    assert all(e["entity_type"] == "CASE" for e in operation_entities)
    assert not [e for e in entities if e["canonical_name"] == "Operation WHITE STRIKE" and e["entity_type"] == "OTHER"]

    cases = client.get("/cases").json()["items"]
    assert any(c.get("case_name") == "Operation WHITE STRIKE" for c in cases)
    assert client.get("/graph/stats").json()["total_edges"] >= 1


# ---------------------------------------------------------------------------
# Timeline (TESTS 13-16)
# ---------------------------------------------------------------------------


def _confirm_first_event(client, event_type: str):
    events = [c for c in _candidates(client) if c["candidate_type"] == "EVENT"]
    target = next(c for c in events if _proposed(c).get("event_type") == event_type)
    resp = client.post(f"/candidates/{target['candidate_id']}/confirm", json={"reason": "reviewed"})
    assert resp.status_code == 200, resp.text
    return target


def test_dated_event_persisted_and_returned_by_timeline(client):
    """TESTS 13 & 14 — the dated DRUG_SEIZURE event is persisted with
    2026-05-01 and returned by the timeline backend."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "white_strike_structured.txt"
    upload_bytes(client, "white_strike_structured.txt", fixture.read_bytes())

    candidate = _confirm_first_event(client, "DRUG_SEIZURE")
    assert _proposed(candidate).get("start_date") == "2026-05-01"

    trusted = client.get("/events?event_type=DRUG_SEIZURE").json()["items"]
    assert len(trusted) == 1
    assert trusted[0]["start_date"] == "2026-05-01"
    assert trusted[0]["date_precision"] == "DAY"

    timeline = client.get("/timeline/global").json()["items"]
    entry = next(e for e in timeline if e.get("event_id") == trusted[0]["event_id"])
    assert entry["date"] == "2026-05-01"
    assert entry["date_precision"] == "DAY"
    assert entry["kind"] == "event"


def test_undated_events_stay_undated(client):
    """TEST 16 — events without an explicit date never inherit the
    document publication date."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "white_strike_structured.txt"
    upload_bytes(client, "white_strike_structured.txt", fixture.read_bytes())

    candidate = _confirm_first_event(client, "VEHICLE_INTERCEPTION")
    assert _proposed(candidate).get("start_date") is None

    timeline = client.get("/timeline/global").json()["items"]
    entry = next(e for e in timeline if e.get("event_type") == "VEHICLE_INTERCEPTION")
    assert entry["date"] is None
    assert entry["date_precision"] == "UNKNOWN"


def test_contextual_official_candidate_is_never_accused(client):
    """REQ 2/3 — a government official PERSON candidate preserves its
    source role/status and is never relabelled ACCUSED/ARRESTED/CONVICTED."""
    upload_bytes(client, "ctx.txt", CONTEXTUAL_PERSON_BLOCK.encode("utf-8"))
    candidates = [
        c for c in _entity_candidates(client)
        if _proposed(c).get("name") == "Amit Shah"
    ]
    assert len(candidates) == 1
    proposed = _proposed(candidates[0])
    assert proposed["entity_type"] == "PERSON"
    assert proposed.get("status") == "GOVERNMENT_OFFICIAL"
    assert proposed.get("status") not in ("ACCUSED", "ARRESTED", "CONVICTED")
    assert proposed.get("role") not in ("ACCUSED", "SUSPECT", "CRIMINAL", "TRAFFICKER")
    # No arrest/conviction fact is invented for a contextual mention.
    items = _candidates(client)
    assert not [c for c in items if c["candidate_type"] == "FACT"]


def test_rejected_event_does_not_enter_timeline(client):
    """TEST E / REQ 17 — a rejected EVENT candidate never appears in the
    trusted timeline; only confirmed events do."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "white_strike_structured.txt"
    upload_bytes(client, "white_strike_structured.txt", fixture.read_bytes())

    events = [c for c in _candidates(client) if c["candidate_type"] == "EVENT"]
    dated = next(c for c in events if _proposed(c).get("event_type") == "DRUG_SEIZURE")
    resp = client.post(f"/candidates/{dated['candidate_id']}/reject", json={"reason": "not supported"})
    assert resp.status_code == 200, resp.text

    # No trusted event row exists for the rejected candidate.
    trusted = client.get("/events").json()["items"]
    assert not [e for e in trusted if e.get("event_type") == "DRUG_SEIZURE"]
    # And no timeline entry references it.
    timeline = client.get("/timeline/global").json()["items"]
    assert not [e for e in timeline if e.get("event_type") == "DRUG_SEIZURE"]

    # A confirmed event from the same document still appears.
    _confirm_first_event(client, "VEHICLE_INTERCEPTION")
    timeline = client.get("/timeline/global").json()["items"]
    assert any(e.get("event_type") == "VEHICLE_INTERCEPTION" for e in timeline)
    assert not [e for e in timeline if e.get("event_type") == "DRUG_SEIZURE"]


def test_multiple_events_keep_individual_dates(client):
    """TEST F — multiple dated events keep their own dates; the document
    publication date is never copied onto undated events."""
    text = (
        "DOCUMENT:\nTITLE: Multi-event report\nDATE: 01 May 2026\n\n"
        "EVENT:\nTYPE: FIRST_SEIZURE\nDATE: 03 March 2026\nLOCATION: Mumbai\n"
        "DESCRIPTION: First seizure occurred in March.\n\n"
        "EVENT:\nTYPE: SECOND_SEIZURE\nDATE: 17 April 2026\nLOCATION: Pune\n"
        "DESCRIPTION: Second seizure occurred in April.\n\n"
        "EVENT:\nTYPE: INTERCEPTION\nLOCATION: Navi Mumbai\n"
        "DESCRIPTION: An interception with no reported date.\n"
    )
    upload_bytes(client, "multi.txt", text.encode("utf-8"))
    for event_type in ("FIRST_SEIZURE", "SECOND_SEIZURE", "INTERCEPTION"):
        _confirm_first_event(client, event_type)

    timeline = client.get("/timeline/global").json()["items"]
    first = next(e for e in timeline if e.get("event_type") == "FIRST_SEIZURE")
    second = next(e for e in timeline if e.get("event_type") == "SECOND_SEIZURE")
    interception = next(e for e in timeline if e.get("event_type") == "INTERCEPTION")
    assert first["date"] == "2026-03-03"
    assert second["date"] == "2026-04-17"
    assert interception["date"] is None
    assert interception["date_precision"] == "UNKNOWN"


def test_timeline_ordering_is_chronological(client):
    """TEST G — dated events are ordered chronologically; undated events
    sort last rather than being dropped or given fabricated dates."""
    text = (
        "EVENT:\nTYPE: LATE_EVENT\nDATE: 10 December 2026\n"
        "DESCRIPTION: Later event.\n\n"
        "EVENT:\nTYPE: EARLY_EVENT\nDATE: 05 January 2026\n"
        "DESCRIPTION: Earlier event.\n\n"
        "EVENT:\nTYPE: UNDATED_EVENT\nDESCRIPTION: No date supplied.\n"
    )
    upload_bytes(client, "order.txt", text.encode("utf-8"))
    for event_type in ("LATE_EVENT", "EARLY_EVENT", "UNDATED_EVENT"):
        _confirm_first_event(client, event_type)

    timeline = client.get("/timeline/global").json()["items"]
    order = [e.get("event_type") for e in timeline]
    assert order.index("EARLY_EVENT") < order.index("LATE_EVENT")
    # The undated event is present (not dropped) and sorted after dated ones.
    assert "UNDATED_EVENT" in order
    dated = [e for e in timeline if e.get("date")]
    assert all(dated[i]["date"] <= dated[i + 1]["date"] for i in range(len(dated) - 1))


def test_structured_candidates_confirm_into_trusted_graph(client):
    """DRUG/VEHICLE/PERSON candidates confirm cleanly into the trusted graph."""
    upload_bytes(client, "white_strike.txt", MINIMAL_DOC.encode("utf-8"))
    by_name = {_proposed(c).get("name"): c for c in _entity_candidates(client)}

    for name in ("Cocaine", "Mumbai", "Person A"):
        candidate = by_name[name]
        resp = client.post(
            f"/candidates/{candidate['candidate_id']}/confirm", json={"reason": "reviewed"}
        )
        assert resp.status_code == 200, resp.text

    entities = client.get("/entities").json()["items"]
    by_canonical = {e["canonical_name"]: e for e in entities}
    assert by_canonical["Cocaine"]["entity_type"] == "DRUG"
    assert by_canonical["Mumbai"]["entity_type"] == "LOCATION"
    assert by_canonical["Person A"]["entity_type"] == "PERSON"
    # Cocaine is a DRUG in the trusted graph — never a PERSON.
    assert by_canonical["Cocaine"]["entity_type"] != "PERSON"


def test_upload_plain_prose_uses_generic_engine(client):
    """Normal unstructured text must keep the existing deterministic path."""
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


# ---------------------------------------------------------------------------
# Entity status preservation (REQ 5/14/15/16) — the semantic distinction
# survives confirmation and is exposed to the graph + node detail panel
# ---------------------------------------------------------------------------


def _confirm_entity(client, name: str) -> dict:
    candidates = [c for c in _entity_candidates(client) if _proposed(c).get("name") == name]
    assert len(candidates) == 1, f"expected one entity candidate for {name}"
    resp = client.post(
        f"/candidates/{candidates[0]['candidate_id']}/confirm", json={"reason": "reviewed"}
    )
    assert resp.status_code == 200, resp.text
    entities = client.get("/entities").json()["items"]
    return next(e for e in entities if e["canonical_name"] == name)


def test_mentioned_person_kept_with_zero_relationships(client):
    """REQ 3/4/5/14 — a mentioned person exists as a trusted node with
    zero relationships. Entity existence never implies a relationship."""
    upload_bytes(client, "mentioned.txt", b"PERSON:\nNAME: Amit Shah\n")
    # No relationship is proposed from the bare mention.
    assert _relationship_candidates(client) == []
    entity = _confirm_entity(client, "Amit Shah")
    assert entity["entity_type"] == "PERSON"
    assert entity["structured_metadata"]["investigative_status"] == "MENTIONED_ONLY"
    # Isolated trusted node: the entity graph returns the node alone.
    graph = client.get(f"/graph/entity/{entity['entity_id']}").json()
    assert len(graph["nodes"]) == 1
    assert graph["edges"] == []
    assert graph["center"]["investigative_status"] == "MENTIONED_ONLY"
    assert client.get("/relationships").json()["total"] == 0
    assert client.get("/graph/stats").json()["total_edges"] == 0


def test_contextual_person_status_preserved_after_confirmation(client):
    """REQ 5/15/16 — a CONTEXTUAL official keeps that status on the trusted
    record and in the graph; the evidence block stays attached."""
    upload_bytes(client, "ctx.txt", CONTEXTUAL_PERSON_BLOCK.encode("utf-8"))
    entity = _confirm_entity(client, "Amit Shah")
    sm = entity["structured_metadata"]
    assert sm["investigative_status"] == "CONTEXTUAL"
    assert sm["role"] == "UNION HOME MINISTER"
    assert sm["status"] == "GOVERNMENT_OFFICIAL"
    assert sm["mention_context"] == "CONTEXTUAL"
    assert "NAME: Amit Shah" in sm["evidence_snippet"]
    # The trusted graph node carries the same semantics for the explorer.
    graph = client.get(f"/graph/entity/{entity['entity_id']}").json()
    assert graph["center"]["investigative_status"] == "CONTEXTUAL"
    assert graph["center"]["mention_context"] == "CONTEXTUAL"
    assert graph["center"]["role"] == "UNION HOME MINISTER"
    # No investigative relationships are invented for the official.
    assert client.get("/relationships").json()["total"] == 0


def test_accused_status_preserved_from_explicit_field(client):
    """REQ 5 — an explicit ACCUSED role/status is preserved as-is; nothing
    is inferred and ARRESTED never becomes CONVICTED."""
    text = "PERSON:\nNAME: John Doe\nROLE: ACCUSED\nSTATUS: ARRESTED\n"
    upload_bytes(client, "accused.txt", text.encode("utf-8"))
    entity = _confirm_entity(client, "John Doe")
    sm = entity["structured_metadata"]
    assert sm["investigative_status"] == "ACCUSED"
    assert sm["status"] == "ARRESTED"
    assert sm["investigative_status"] != "CONVICTED"
    # No mention context was supplied, so none is invented.
    assert sm.get("mention_context") is None


def test_multiple_mentioned_people_no_relationships(client):
    """REQ 4/8 — several mentioned people all become PERSON nodes with zero
    relationships; co-occurrence in one document creates nothing."""
    text = (
        "PERSON:\nNAME: Amit Shah\n\n"
        "PERSON:\nNAME: Narendra Modi\n\n"
        "PERSON:\nNAME: Person A\n\n"
        "DRUG:\nNAME: Cocaine\n"
    )
    upload_bytes(client, "multi_people.txt", text.encode("utf-8"))
    people = [
        c for c in _entity_candidates(client)
        if _proposed(c).get("entity_type") == "PERSON"
    ]
    assert {_proposed(c).get("name") for c in people} == {"Amit Shah", "Narendra Modi", "Person A"}
    assert _relationship_candidates(client) == []


def test_relationship_provenance_includes_source_and_target(client):
    """REQ 10/17 — provenance exposes the source and target names/types of
    a confirmed relationship alongside evidence, confidence and document."""
    upload_bytes(client, "rel.txt", RELATIONSHIP_DOC.encode("utf-8"))
    rel = _relationship_candidates(client)[0]
    resp = client.post(f"/candidates/{rel['candidate_id']}/confirm", json={"reason": "reviewed"})
    assert resp.status_code == 200, resp.text

    trusted = client.get("/relationships").json()["items"]
    assert len(trusted) == 1
    prov = client.get(
        f"/graph/provenance/relationship/{trusted[0]['relationship_id']}"
    ).json()
    assert prov["relationship_type"] == "ARRESTED"
    assert prov["source_name"] == "Narcotics Control Bureau"
    assert prov["source_type"] == "ORGANIZATION"
    assert prov["target_name"] == "John Doe"
    assert prov["target_type"] == "PERSON"
    assert prov["relationship"]["confidence"] is not None
    # The exact structured block is retained as evidence.
    assert prov["evidence"] is not None
    assert "RELATIONSHIP" in prov["evidence"]["exact_text"]
