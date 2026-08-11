"""ENTITY NORMALIZATION, CONFIDENCE SEMANTICS AND ALLEGATION TESTS.

Regression tests for the exact live-app failure:

    "The Directorate of Revenue Intelligence and the Customs Department
     also participated in Operation Bluewater."

must produce ONLY the full organization spans (Directorate of Revenue
Intelligence, Customs Department) — never the fragments "Directorate"
(ORGANIZATION) or "Revenue Intelligence" (PERSON). Suppression is based
on span containment, so standalone words ("The Directorate issued a
notice.") still survive and distinct organizations are never merged.

Also verifies the API labels confidence as extraction/matching
confidence (never a probability of guilt) and that allegations stay
classified as ALLEGED.
"""

from app.services.extraction.engine import run_extraction
from app.tests.conftest import make_txt_bytes, upload_bytes


def _org_names(result) -> set[str]:
    return {e.name for e in result.entities if e.entity_type == "ORGANIZATION"}


def _person_names(result) -> set[str]:
    return {e.name for e in result.entities if e.entity_type == "PERSON"}


def _names(result) -> set[tuple[str, str]]:
    return {(e.entity_type, e.name) for e in result.entities}


# ---------------------------------------------------------------------------
# Test 1 — the exact live-app sentence
# ---------------------------------------------------------------------------

def test_1_live_sentence_full_orgs_only():
    result = run_extraction(
        "The Directorate of Revenue Intelligence and the Customs Department also "
        "participated in Operation Bluewater."
    )
    orgs = _org_names(result)
    assert "Directorate of Revenue Intelligence" in orgs
    assert "Customs Department" in orgs
    # The generic fragments must not survive.
    assert "Directorate" not in orgs
    assert "Customs" not in orgs


# ---------------------------------------------------------------------------
# Test 2 — no person-shaped fragment from the organization name
# ---------------------------------------------------------------------------

def test_2_no_person_fragment_from_org_name():
    result = run_extraction(
        "The Directorate of Revenue Intelligence and the Customs Department also "
        "participated in Operation Bluewater."
    )
    persons = _person_names(result)
    assert "Revenue Intelligence" not in persons
    assert "Directorate" not in persons
    assert ("PERSON", "Revenue Intelligence") not in _names(result)


# ---------------------------------------------------------------------------
# Line-break inside the org name (PDF/DOCX extraction artifacts)
# ---------------------------------------------------------------------------

def test_org_name_across_line_break_still_wins():
    """A line break inside the organization name must not strand the fragments."""
    result = run_extraction(
        "The Directorate of Revenue\nIntelligence and the Customs Department also "
        "participated in Operation Bluewater."
    )
    orgs = _org_names(result)
    assert "Directorate of Revenue Intelligence" in orgs
    assert "Directorate" not in orgs
    assert "Revenue Intelligence" not in _person_names(result)


# ---------------------------------------------------------------------------
# Test 3 — standalone generic word is preserved
# ---------------------------------------------------------------------------

def test_3_standalone_directorate_kept():
    result = run_extraction("The Directorate issued a notice.")
    orgs = _org_names(result)
    assert "Directorate" in orgs


# ---------------------------------------------------------------------------
# Test 4 — normal person extraction still works
# ---------------------------------------------------------------------------

def test_4_person_name_still_extracted():
    result = run_extraction("Arjun Mehta was arrested during Operation Alpha.")
    names = _names(result)
    assert ("PERSON", "Arjun Mehta") in names
    assert ("OTHER", "Operation Alpha") in names


# ---------------------------------------------------------------------------
# Test 5 — Central Bureau of Investigation
# ---------------------------------------------------------------------------

def test_5_cbi_full_name_only():
    result = run_extraction("Central Bureau of Investigation investigated the case.")
    orgs = _org_names(result)
    persons = _person_names(result)
    assert "Central Bureau of Investigation" in orgs
    assert "Bureau" not in orgs
    assert "Investigation" not in persons


# ---------------------------------------------------------------------------
# Test 6 — Narcotics Control Bureau
# ---------------------------------------------------------------------------

def test_6_ncb_full_name_only():
    result = run_extraction("Narcotics Control Bureau participated in the operation.")
    orgs = _org_names(result)
    assert "Narcotics Control Bureau" in orgs
    assert "Bureau" not in orgs


# ---------------------------------------------------------------------------
# Test 7 — two distinct organizations stay separate
# ---------------------------------------------------------------------------

def test_7_two_directorates_not_merged():
    result = run_extraction(
        "Directorate of Revenue Intelligence and Directorate General of GST Intelligence participated."
    )
    orgs = _org_names(result)
    assert "Directorate of Revenue Intelligence" in orgs
    assert "Directorate General of GST Intelligence" in orgs
    assert "Directorate" not in orgs


# ---------------------------------------------------------------------------
# Confidence semantics (Fix 2 — unchanged wording)
# ---------------------------------------------------------------------------

def test_confidence_meaning_on_candidates(client):
    upload_bytes(
        client,
        "confidence.txt",
        make_txt_bytes(
            "Arjun Mehta was arrested during Operation Bluewater in Mumbai on 15 June 2026."
        ),
    )
    items = client.get("/candidates").json()["items"]
    pending = [c for c in items if c["status"] == "PENDING"]
    assert pending, "expected candidates after processing"
    scored = next(c for c in pending if c.get("confidence") is not None)
    meaning = scored.get("confidence_meaning")
    assert meaning, "confidence_meaning must be present for scored candidates"
    assert "not a probability of guilt" in meaning
    assert "extraction" in meaning.lower() or "match" in meaning.lower()


# ---------------------------------------------------------------------------
# Allegations remain allegations (Fix 3)
# ---------------------------------------------------------------------------

def test_allegation_stays_alleged():
    result = run_extraction("Authorities alleged that Vikram Jadhav supplied materials.")
    alleged = [c for c in result.claims if c.claim_status == "ALLEGED"]
    assert alleged, "expected an ALLEGED claim"
    assert "alleged" in alleged[0].claim_text.lower()
