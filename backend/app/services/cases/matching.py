"""Case matching foundation.

  * exact official case number -> suggested existing case
  * no match                   -> candidate new case
  * case name only matches     -> POSSIBLE MATCH, human confirmation required

Cases are never merged automatically just because numbers or names look
similar.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models.case import Case
from app.utils.text import normalize_case_number

CASE_MATCH_EXACT_NUMBER = "exact_number"
CASE_MATCH_POSSIBLE_NAME = "possible_name"
CASE_MATCH_NONE = "none"


def find_exact_case(db: Session, case_number: str | None) -> Case | None:
    if not case_number:
        return None
    normalized = normalize_case_number(case_number)
    for case in db.query(Case).all():
        if case.official_case_number and normalize_case_number(case.official_case_number) == normalized:
            return case
    return None


def find_possible_case_name_matches(db: Session, case_name: str | None, threshold: float = 0.6) -> list[Case]:
    if not case_name:
        return []
    matches = []
    normalized = normalize_case_number(case_name)
    for case in db.query(Case).all():
        candidate = case.case_name or case.operation_name or ""
        if not candidate:
            continue
        ratio = SequenceMatcher(None, normalized, normalize_case_number(candidate)).ratio()
        if ratio >= threshold:
            matches.append(case)
    return matches


def match_case(
    db: Session, *, case_number: str | None, case_name: str | None
) -> tuple[str | None, str]:
    """Returns ``(existing_case_id, match_kind)``.

    match_kind is one of exact_number / possible_name / none.
    """
    existing = find_exact_case(db, case_number)
    if existing is not None:
        return existing.case_id, CASE_MATCH_EXACT_NUMBER

    if case_number:
        # A provided official number that matches no existing case is
        # contradictory evidence (RULE 10): never fall back to fuzzy
        # name matching for it.
        return None, CASE_MATCH_NONE

    if case_name:
        possible = find_possible_case_name_matches(db, case_name)
        if possible:
            return possible[0].case_id, CASE_MATCH_POSSIBLE_NAME
    return None, CASE_MATCH_NONE
