"""CLAIM TESTS — allegations must remain allegations."""

from app.services.extraction.engine import run_extraction


def test_alleged_claim():
    result = run_extraction(
        "Authorities alleged that Karan Shah coordinated with Silverline Traders."
    )
    claim = next(c for c in result.claims)
    assert claim.claim_status == "ALLEGED"
    assert claim.subject_name == "Karan Shah"


def test_reported_claim():
    result = run_extraction("Reportedly, Arjun Mehta was seen in Mumbai.")
    claim = next(c for c in result.claims)
    assert claim.claim_status == "REPORTED"


def test_officially_stated_claim():
    result = run_extraction("Officially stated: the next hearing is scheduled for August 2026.")
    claim = next(c for c in result.claims)
    assert claim.claim_status == "OFFICIALLY_STATED"


def test_court_recorded_claim():
    result = run_extraction("The court recorded that Kavita Rao will preside over the hearing.")
    claim = next(c for c in result.claims)
    assert claim.claim_status == "COURT_RECORDED"


def test_allegation_is_not_a_confirmed_fact():
    result = run_extraction(
        "Authorities alleged that Karan Shah coordinated with Silverline Traders."
    )
    # No INVOLVED_IN/ASSOCIATED relationship from the allegation alone.
    assert result.relationships == []
