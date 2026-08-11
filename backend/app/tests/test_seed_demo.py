"""SEED DEMO IDEMPOTENCY TESTS.

Regression for the live failure:

    python scripts/seed_demo.py
    -> CandidateStateError: Candidate is not in a reviewable state.

Root cause: seed_demo() confirmed candidates without checking their state,
so re-running it against a database that already contained CONFIRMED
candidates (a previous seed) tried to confirm them again and crashed.

The fix filters every confirm loop to reviewable states (PENDING/EDITED)
and guards the derived candidate, so re-seeding a populated database is a
safe no-op that respects the candidate state machine. confirm_candidate()
itself is unchanged.

Seed summary semantics (verified against seed_demo()):

  summary.documents  == number of demo documents processed through the
                       pipeline (DEMO_DOCUMENTS, 10 entries). The exact
                       duplicate is a separate upload tracked by
                       summary.duplicates — the counter is NOT the
                       documents-table row count.
  documents table    == 10 processed originals + 1 DUPLICATE row after a
                       fresh seed (11 rows total). No record is skipped.

Second-run idempotency: the seed never re-uploads a demo document that is
already present (stable demo filename), so a re-seed cannot re-process any
file — regardless of whether regenerated PDF/DOCX bytes are byte-identical.
The PDF/DOCX builders also pin fixed timestamps as defense in depth. The
explicit duplicate upload still exercises SHA-256 duplicate detection on
every run (the 11-vs-9 / 20-vs-18 regressions).
"""

import pytest

from app.models.document import STATUS_DUPLICATE, Document
from app.services.demo.seed import seed_demo


def test_seed_demo_is_idempotent(db):
    # First seed populates the database through the real upload pipeline.
    first = seed_demo(db)
    assert first.documents == 10  # the 10 demo documents (README: "10 documents including one exact duplicate")
    assert first.duplicates == 1  # the exact duplicate upload
    assert first.confirmed_candidates > 0
    assert first.pending_candidates >= 1  # derived relationship stays PENDING

    # DB state after the first seed: every demo document is recorded AND the
    # exact duplicate is stored as a DUPLICATE row referencing the original.
    docs = db.query(Document).all()
    assert len(docs) == 11, "expected 10 processed originals + 1 duplicate row"
    dup_rows = [d for d in docs if d.processing_status == STATUS_DUPLICATE]
    assert len(dup_rows) == 1
    assert dup_rows[0].duplicate_of_document_id is not None

    # Second seed against the SAME database must not raise
    # CandidateStateError and must not re-confirm or alter trusted data.
    second = seed_demo(db)
    assert second.documents == first.documents == 10
    assert second.people == first.people
    assert second.organizations == first.organizations
    assert second.locations == first.locations
    assert second.events == first.events
    assert second.cases == first.cases
    assert second.relationships == first.relationships
    assert second.facts == first.facts
    assert second.claims == first.claims
    assert second.pending_candidates == first.pending_candidates

    # Idempotency check (regression: 11 vs 9). After the second seed the
    # documents table must still contain exactly the 10 demo originals —
    # nothing may be re-processed — plus one DUPLICATE row per run's
    # explicit duplicate upload (2 total): 12 rows, 10 non-duplicates,
    # 2 duplicates. No duplicate trusted records may be created.
    docs_after = db.query(Document).all()
    non_dup = [d for d in docs_after if d.processing_status != STATUS_DUPLICATE]
    dup_after = [d for d in docs_after if d.processing_status == STATUS_DUPLICATE]
    assert len(non_dup) == 10, "no demo original may be re-processed on re-seed"
    assert len(dup_after) == 2, (
        "expected 2 duplicate rows after two seeds "
        "(one explicit duplicate upload per run)"
    )


def test_seed_demo_never_auto_confirms_possible_match(db):
    """The seed must never confirm a POSSIBLE_MATCH candidate."""
    seed_demo(db)
    from app.models.candidate import Candidate

    possible_matches = [
        c for c in db.query(Candidate).all()
        if (c.proposed_data or {}).get("relationship_type") == "POSSIBLE_MATCH"
    ]
    # The demo content has no identity-match scenario; if one ever appears,
    # it must remain PENDING/CANDIDATE — never CONFIRMED by the seed.
    for candidate in possible_matches:
        assert candidate.status != "CONFIRMED"
        assert (candidate.proposed_data or {}).get("classification") == "CANDIDATE"


def test_seed_demo_without_explicit_session(db):
    """seed_demo() also works when it manages its own session (the exact
    path scripts/seed_demo.py uses), against the same database file."""
    summary = seed_demo()
    assert summary.documents == 10
    assert summary.duplicates == 1
