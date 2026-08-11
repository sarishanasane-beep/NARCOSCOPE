"""ENTITY MATCH TESTS — entity-resolution foundation."""

from app.services.entities.matching import (
    MATCH_KEEP_SEPARATE,
    MATCH_POSSIBLE,
    MATCH_STRONG,
    score_match,
)
from app.services.entities.resolution import create_entity


def test_strong_match(db):
    create_entity(
        db,
        entity_type="PERSON",
        canonical_name="Sameer Kulkarni",
        aliases=["S. Kulkarni"],
    )
    db.commit()
    matches = score_match(
        db,
        name="Sameer Kulkarni",
        entity_type="PERSON",
        aliases=["S. Kulkarni"],
    )
    assert matches
    best = matches[0]
    assert best.verdict == MATCH_STRONG
    assert best.score >= 85


def test_possible_match_same_name(db):
    create_entity(db, entity_type="PERSON", canonical_name="Arjun Mehta")
    db.commit()
    matches = score_match(db, name="Arjun Mehta", entity_type="PERSON")
    assert matches
    best = matches[0]
    # Same full name is POSSIBLE_MATCH — human confirmation still required.
    assert best.verdict == MATCH_POSSIBLE
    assert 60 <= best.score < 85


def test_different_people_same_surname(db):
    create_entity(db, entity_type="PERSON", canonical_name="Arun Patil")
    db.commit()
    matches = score_match(db, name="Suresh Patil", entity_type="PERSON")
    assert matches == [] or all(m.verdict == MATCH_KEEP_SEPARATE for m in matches)


def test_different_people_same_full_name_requires_human(db):
    # Two different people can share a full name — the matcher must never
    # return STRONG without additional signals.
    create_entity(db, entity_type="PERSON", canonical_name="Vikram Jadhav")
    db.commit()
    matches = score_match(db, name="Vikram Jadhav", entity_type="PERSON")
    assert matches
    assert matches[0].verdict != MATCH_STRONG


def test_location_context_raises_score(db):
    create_entity(
        db,
        entity_type="PERSON",
        canonical_name="Rohit Mane",
        notes="resides in Thane",
    )
    db.commit()
    matches = score_match(
        db,
        name="Rohit Mane",
        entity_type="PERSON",
        location="Thane",
    )
    assert matches
    assert matches[0].score >= 60
