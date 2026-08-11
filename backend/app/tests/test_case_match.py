"""CASE MATCH TESTS."""

import uuid

from app.models.case import Case
from app.services.cases.matching import (
    CASE_MATCH_EXACT_NUMBER,
    CASE_MATCH_NONE,
    CASE_MATCH_POSSIBLE_NAME,
    find_exact_case,
    find_possible_case_name_matches,
    match_case,
)


def _case(db, number=None, name=None, operation=None):
    case = Case(
        case_id=str(uuid.uuid4()),
        official_case_number=number,
        case_name=name,
        operation_name=operation,
    )
    db.add(case)
    db.flush()
    return case


def test_exact_case_number_match(db):
    _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    db.commit()
    found = find_exact_case(db, "ncb/mum/123/2026")
    assert found is not None
    assert found.case_name == "CASE-001"


def test_exact_match_returns_link(db):
    _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    db.commit()
    existing_id, kind = match_case(db, case_number="NCB/MUM/123/2026", case_name="CASE-001")
    assert kind == CASE_MATCH_EXACT_NUMBER
    assert existing_id is not None


def test_possible_case_name_match(db):
    _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    db.commit()
    existing_id, kind = match_case(db, case_number=None, case_name="CASE-001")
    assert kind == CASE_MATCH_POSSIBLE_NAME
    assert existing_id is not None
    # Human confirmation is required for name-only matches.
    assert find_possible_case_name_matches(db, "CASE-001")


def test_different_cases_no_match(db):
    _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    db.commit()
    existing_id, kind = match_case(db, case_number="XYZ/999/2027", case_name="CASE-099")
    assert kind == CASE_MATCH_NONE
    assert existing_id is None


def test_similar_numbers_are_not_merged(db):
    first = _case(db, number="NCB/MUM/123/2026", name="CASE-001")
    second = _case(db, number="NCB/MUM/124/2026", name="CASE-002")
    db.commit()
    assert first.case_id != second.case_id
    found = find_exact_case(db, "NCB/MUM/123/2026")
    assert found.case_id == first.case_id
