"""VALIDATION TESTS — the candidate review workflow."""

import uuid

from app.models.candidate import Candidate
from app.models.entity import Entity
from app.services.audit.service import log_action, list_audit
from app.services.candidates.service import get_candidate, update_candidate
from app.services.validation.workflow import confirm_candidate
from app.utils.errors import CandidateStateError


def _entity_candidate(db, name="Arjun Mehta", candidate_type="ENTITY"):
    candidate = Candidate(
        candidate_id=str(uuid.uuid4()),
        candidate_type=candidate_type,
        proposed_data={"name": name, "entity_type": "PERSON", "aliases": []},
        reason="test candidate",
        status="PENDING",
    )
    db.add(candidate)
    db.flush()
    return candidate


def test_candidate_creation(db):
    candidate = _entity_candidate(db)
    db.commit()
    fetched = get_candidate(db, candidate.candidate_id)
    assert fetched.status == "PENDING"
    assert fetched.proposed_data["name"] == "Arjun Mehta"


def test_candidate_confirmation(db):
    candidate = _entity_candidate(db)
    confirm_candidate(db, candidate, reviewed_by="tester", reason="looks right")
    db.commit()

    assert candidate.status == "CONFIRMED"
    assert candidate.reviewed_by == "tester"

    entity = db.query(Entity).filter(Entity.canonical_name == "Arjun Mehta").first()
    assert entity is not None
    assert entity.entity_type == "PERSON"

    actions = [a.action for a in list_audit(db)]
    assert "CONFIRM" in actions


def test_candidate_confirmation_with_edits(db):
    candidate = _entity_candidate(db)
    confirm_candidate(
        db,
        candidate,
        reviewed_by="tester",
        edits={"aliases": ["A. Mehta"]},
    )
    db.commit()
    assert candidate.status == "CONFIRMED"
    assert candidate.proposed_data["aliases"] == ["A. Mehta"]
    entity = db.query(Entity).filter(Entity.canonical_name == "Arjun Mehta").first()
    assert "A. Mehta" in entity.person.aliases


def test_candidate_rejection(db):
    candidate = _entity_candidate(db, name="Noise Person")
    from app.services.candidates.service import reject_candidate

    reject_candidate(db, candidate, reviewed_by="tester", reason="not supported by source")
    db.commit()

    assert candidate.status == "REJECTED"
    # Rejected candidate must NOT enter trusted data.
    entity = db.query(Entity).filter(Entity.canonical_name == "Noise Person").first()
    assert entity is None
    # But the candidate record is preserved in history.
    assert get_candidate(db, candidate.candidate_id).status == "REJECTED"


def test_candidate_edit(db):
    candidate = _entity_candidate(db, name="Sameer Kulkarni")
    update_candidate(
        db,
        candidate,
        proposed_data={"name": "Sameer Kulkarni", "entity_type": "PERSON", "aliases": ["S. Kulkarni"]},
        reason="added alias",
    )
    db.commit()
    assert candidate.status == "EDITED"
    assert candidate.proposed_data["aliases"] == ["S. Kulkarni"]


def test_confirm_rejected_candidate_fails(db):
    from app.services.candidates.service import reject_candidate

    candidate = _entity_candidate(db)
    reject_candidate(db, candidate, reason="no")
    db.commit()
    import pytest

    with pytest.raises(CandidateStateError):
        confirm_candidate(db, candidate)
