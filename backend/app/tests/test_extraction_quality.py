"""EXTRACTION QUALITY TESTS.

Covers: false-person rejection (Officially, Case No), preservation of
valid person extraction, one-canonical-entity deduplication with
multiple evidence references, deterministic entity resolution
(POSSIBLE_MATCH candidates, never auto-merge), organization handling
(Organization X, full names win) and the earlier normalization
guarantees.
"""

from app.services.extraction.engine import run_extraction
from app.tests.conftest import make_txt_bytes, upload_bytes


def _names(result) -> set[tuple[str, str]]:
    return {(e.entity_type, e.name) for e in result.entities}


def _person_names(result) -> set[str]:
    return {e.name for e in result.entities if e.entity_type == "PERSON"}


def _org_names(result) -> set[str]:
    return {e.name for e in result.entities if e.entity_type == "ORGANIZATION"}


# ---------------------------------------------------------------------------
# A — "Officially" is not a person
# ---------------------------------------------------------------------------

def test_a_officially_not_person():
    result = run_extraction("Officially stated that the next hearing is scheduled for August 2026.")
    assert ("PERSON", "Officially") not in _names(result)


# ---------------------------------------------------------------------------
# B — "Case No" is not a person
# ---------------------------------------------------------------------------

def test_b_case_no_not_person():
    result = run_extraction("The reference is Case No. CASE-TEST-001.")
    assert "Case No" not in _person_names(result)
    assert "Case" not in _person_names(result)


# ---------------------------------------------------------------------------
# C — valid person extraction still works
# ---------------------------------------------------------------------------

def test_c_arjun_mehta_person():
    result = run_extraction("Arjun Mehta was arrested during Operation Alpha.")
    assert ("PERSON", "Arjun Mehta") in _names(result)


# ---------------------------------------------------------------------------
# D — titled person still works
# ---------------------------------------------------------------------------

def test_d_titled_person():
    result = run_extraction("Inspector Suresh Patil led Operation Bluewater.")
    names = _names(result)
    assert ("PERSON", "Suresh Patil") in names
    assert ("OTHER", "Operation Bluewater") in names


# ---------------------------------------------------------------------------
# E — one canonical candidate, multiple evidence references (two documents)
# ---------------------------------------------------------------------------

def test_e_same_entity_two_documents_one_candidate(client):
    upload_bytes(
        client, "doc1.txt",
        make_txt_bytes("Inspector Suresh Patil led Operation Bluewater in Mumbai."),
    )
    upload_bytes(
        client, "doc2.txt",
        make_txt_bytes("Inspector Suresh Patil was questioned in connection with Case CASE-001."),
    )
    items = client.get("/candidates").json()["items"]
    suresh = [
        c for c in items
        if c["candidate_type"] in ("ENTITY", "LOCATION")
        and c["proposed_data"].get("name") == "Suresh Patil"
    ]
    assert len(suresh) == 1, f"expected one canonical candidate, got {len(suresh)}"
    refs = suresh[0].get("evidence_refs") or []
    assert len(refs) >= 2, "expected one evidence reference per document"
    texts = {r["exact_text"] for r in refs}
    assert any("led Operation Bluewater" in t for t in texts)
    assert any("questioned in connection" in t for t in texts)


# ---------------------------------------------------------------------------
# F, G, H — organization normalization guarantees hold
# ---------------------------------------------------------------------------

def test_f_dri_full_name_wins():
    result = run_extraction(
        "Directorate of Revenue Intelligence participated in Operation Bluewater."
    )
    assert "Directorate of Revenue Intelligence" in _org_names(result)
    assert "Directorate" not in _org_names(result)
    assert "Revenue Intelligence" not in _person_names(result)


def test_g_cbi_full_name_wins():
    result = run_extraction("Central Bureau of Investigation investigated the case.")
    assert "Central Bureau of Investigation" in _org_names(result)
    assert "Bureau" not in _org_names(result)
    assert "Investigation" not in _person_names(result)


def test_h_ncb_full_name_wins():
    result = run_extraction("Narcotics Control Bureau participated in the operation.")
    assert "Narcotics Control Bureau" in _org_names(result)
    assert "Bureau" not in _org_names(result)


# ---------------------------------------------------------------------------
# I — "Organization X" keeps the meaningful span
# ---------------------------------------------------------------------------

def test_i_organization_x_kept_as_span():
    result = run_extraction("Organization X was mentioned in the investigation.")
    orgs = _org_names(result)
    assert "Organization X" in orgs
    assert "Organization" not in orgs
    assert ("PERSON", "Organization X") not in _names(result)


# ---------------------------------------------------------------------------
# Organization labels — the word before the colon is a label, not the name
# ---------------------------------------------------------------------------

def test_org_label_full_name_taken_from_after_colon():
    result = run_extraction("Organization profile: Blue Horizon Imports.")
    orgs = _org_names(result)
    assert "Blue Horizon Imports" in orgs
    assert "Organization" not in orgs
    assert ("PERSON", "Blue Horizon Imports") not in _names(result)


def test_org_label_variants():
    result = run_extraction(
        "Company: Acme Trading Ltd. Agency: Blue Sky Logistics. "
        "Organization: Redline Logistics."
    )
    orgs = _org_names(result)
    assert "Acme Trading Ltd" in orgs
    assert "Blue Sky Logistics" in orgs
    assert "Redline Logistics" in orgs
    # The label words themselves are not organizations.
    assert "Company" not in orgs
    assert "Agency" not in orgs
    assert "Organization" not in orgs


def test_org_label_full_suffix_kept():
    # "Company profile: <full name>" keeps the complete name including
    # suffixes, without the trailing period.
    result = run_extraction("Company profile: Blue Horizon Industries Ltd.")
    orgs = _org_names(result)
    assert "Blue Horizon Industries Ltd" in orgs
    assert "Company" not in orgs
    assert "Blue Horizon" not in orgs
    assert "Blue Horizon Industries" not in orgs


def test_org_label_does_not_break_placeholder_form():
    # "Organization X" (no colon) is a placeholder entity, not a label.
    result = run_extraction("Organization X was mentioned in the investigation.")
    orgs = _org_names(result)
    assert "Organization X" in orgs
    assert "Organization" not in orgs


def test_standalone_label_word_still_an_organization():
    # Without a colon, "The Agency issued a notice." keeps the word.
    result = run_extraction("The Agency issued a notice.")
    assert "Agency" in _org_names(result)


# ---------------------------------------------------------------------------
# Same entity twice in ONE document — both occurrences become evidence refs
# ---------------------------------------------------------------------------

def test_same_entity_twice_in_one_document_two_evidence_refs(client):
    upload_bytes(
        client, "one.txt",
        make_txt_bytes(
            "Arjun Mehta was arrested during Operation Bluewater. "
            "Arjun Mehta was also questioned in connection with Case CASE-001."
        ),
    )
    items = client.get("/candidates").json()["items"]
    arjun = [
        c for c in items
        if c["candidate_type"] in ("ENTITY", "LOCATION")
        and c["proposed_data"].get("name") == "Arjun Mehta"
    ]
    assert len(arjun) == 1, f"expected one canonical candidate, got {len(arjun)}"
    refs = arjun[0].get("evidence_refs") or []
    assert len(refs) >= 2, "expected one evidence reference per occurrence"
    texts = {r["exact_text"] for r in refs}
    assert any("was arrested" in t for t in texts)
    assert any("questioned in connection" in t for t in texts)


# ---------------------------------------------------------------------------
# Entity resolution — POSSIBLE_MATCH, never auto-merge
# ---------------------------------------------------------------------------

def test_possible_match_created_for_initial_form():
    result = run_extraction(
        "Suresh Patil coordinated the raid on 10 June 2026. S. Patil also participated."
    )
    rels = {(r.source_name, r.relationship_type, r.target_name) for r in result.relationships}
    assert ("Suresh Patil", "POSSIBLE_MATCH", "S. Patil") in rels
    assert all(r.classification == "CANDIDATE" for r in result.relationships
               if r.relationship_type == "POSSIBLE_MATCH")


def test_same_sentence_alias_still_merges_not_possible_match():
    """Explicit same-sentence aliases still become aliases — no POSSIBLE_MATCH."""
    result = run_extraction(
        "Sameer Kulkarni is also referred to as S. Kulkarni in some records."
    )
    persons = [e for e in result.entities if e.entity_type == "PERSON"]
    assert len(persons) == 1
    assert "S. Kulkarni" in persons[0].aliases
    assert not [r for r in result.relationships if r.relationship_type == "POSSIBLE_MATCH"]


def _possible_matches(items):
    return [
        c for c in items
        if c["candidate_type"] == "RELATIONSHIP"
        and c["proposed_data"].get("relationship_type") == "POSSIBLE_MATCH"
    ]


def test_cross_document_possible_match(client):
    """Full form first, variant in a later document -> one POSSIBLE_MATCH."""
    upload_bytes(
        client, "doc_a.txt",
        make_txt_bytes("Inspector Suresh Patil led Operation Bluewater."),
    )
    upload_bytes(client, "doc_b.txt", make_txt_bytes("S. Patil attended the hearing."))
    items = client.get("/candidates").json()["items"]

    # Both forms remain separate PERSON candidates — never auto-merged.
    names = [
        c["proposed_data"].get("name")
        for c in items
        if c["candidate_type"] in ("ENTITY", "LOCATION")
        and c["proposed_data"].get("entity_type") == "PERSON"
    ]
    assert "Suresh Patil" in names
    assert "S. Patil" in names

    possible = _possible_matches(items)
    assert len(possible) == 1, f"expected exactly one POSSIBLE_MATCH, got {len(possible)}"
    rel = possible[0]["proposed_data"]
    assert rel["source_name"] == "Suresh Patil"
    assert rel["target_name"] == "S. Patil"
    assert rel["classification"] == "CANDIDATE"
    assert possible[0]["confidence"] == 0.6
    assert "Human confirmation is required" in possible[0]["reason"]


def test_no_possible_match_for_exact_name_across_documents(client):
    """Exact canonical names across documents merge — never POSSIBLE_MATCH."""
    upload_bytes(
        client, "doc_a.txt",
        make_txt_bytes("Inspector Suresh Patil led Operation Bluewater."),
    )
    upload_bytes(
        client, "doc_b.txt",
        make_txt_bytes("Inspector Suresh Patil was questioned in connection with Case CASE-001."),
    )
    items = client.get("/candidates").json()["items"]
    assert _possible_matches(items) == []


def test_cross_document_possible_match_reverse_order(client):
    """Variant first, full form later -> still full -> variant direction."""
    upload_bytes(client, "doc_a.txt", make_txt_bytes("S. Patil attended the hearing."))
    upload_bytes(
        client, "doc_b.txt",
        make_txt_bytes("Inspector Suresh Patil led Operation Bluewater."),
    )
    items = client.get("/candidates").json()["items"]

    possible = _possible_matches(items)
    assert len(possible) == 1, f"expected exactly one POSSIBLE_MATCH, got {len(possible)}"
    rel = possible[0]["proposed_data"]
    assert rel["source_name"] == "Suresh Patil"
    assert rel["target_name"] == "S. Patil"
    assert rel["classification"] == "CANDIDATE"
    assert possible[0]["confidence"] == 0.6
    assert "Human confirmation is required" in possible[0]["reason"]
