"""Entity matching (entity-resolution foundation).

Possible signals, weighted:
  * name similarity           40%
  * alias / context similarity 25%
  * location similarity        15%
  * organization/context       20%

An exact normalized-name match receives a bonus (+25) because it is a
strong signal — but human confirmation is STILL required before any
merge. Thresholds:

  0–59    KEEP SEPARATE
  60–84   POSSIBLE MATCH -> human review
  85–100  STRONG MATCH -> human confirmation still required

NARCOSCOPE NEVER automatically merges uncertain people.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models.entity import Entity, ENTITY_STATUS_ACTIVE
from app.models.location import Location
from app.models.organization import Organization
from app.models.person import Person
from app.utils.text import normalize_name

MATCH_KEEP_SEPARATE = "KEEP_SEPARATE"
MATCH_POSSIBLE = "POSSIBLE_MATCH"
MATCH_STRONG = "STRONG_MATCH"

THRESHOLD_POSSIBLE = 60
THRESHOLD_STRONG = 85

_WEIGHT_NAME = 0.40
_WEIGHT_ALIAS = 0.25
_WEIGHT_LOCATION = 0.15
_WEIGHT_CONTEXT = 0.20
_EXACT_NAME_BONUS = 25


@dataclass
class MatchResult:
    entity_id: str
    name: str
    score: float
    verdict: str
    signals: dict = field(default_factory=dict)


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def _max_overlap(candidate: list[str], existing: list[str]) -> float:
    if not candidate or not existing:
        return 0.0
    best = 0.0
    for c in candidate:
        for e in existing:
            best = max(best, SequenceMatcher(None, normalize_name(c), normalize_name(e)).ratio())
    return best


def score_match(
    db: Session,
    *,
    name: str,
    entity_type: str,
    aliases: list[str] | None = None,
    location: str | None = None,
    context: str | None = None,
    limit: int = 10,
    exclude_entity_id: str | None = None,
) -> list[MatchResult]:
    """Score a candidate entity against existing active entities.

    Returns matches sorted by score descending with a verdict:
    KEEP_SEPARATE / POSSIBLE_MATCH / STRONG_MATCH. An identical name
    yields POSSIBLE_MATCH (human confirmation still required); extra
    signals (aliases, location, context) can raise it to STRONG_MATCH.
    """
    normalized = normalize_name(name)
    results: list[MatchResult] = []

    entities = (
        db.query(Entity)
        .filter(Entity.entity_type == entity_type, Entity.status == ENTITY_STATUS_ACTIVE)
        .all()
    )
    for existing in entities:
        if existing.entity_id == exclude_entity_id:
            continue
        existing_name = existing.canonical_name

        name_score = name_similarity(name, existing_name)
        alias_score = _max_overlap(aliases or [], _aliases_of(db, existing))
        location_score = 0.0
        if location and entity_type == "PERSON":
            existing_location = _person_location(db, existing)
            if existing_location:
                location_score = SequenceMatcher(
                    None, normalize_name(location), normalize_name(existing_location)
                ).ratio()
        context_score = 0.0
        if context and entity_type == "ORGANIZATION":
            context_score = SequenceMatcher(
                None, normalize_name(context), normalize_name(existing_name)
            ).ratio()

        score = (
            _WEIGHT_NAME * name_score
            + _WEIGHT_ALIAS * alias_score
            + _WEIGHT_LOCATION * location_score
            + _WEIGHT_CONTEXT * context_score
        ) * 100
        if normalized == normalize_name(existing_name):
            score = min(100.0, score + _EXACT_NAME_BONUS)

        verdict = _verdict(score)
        results.append(
            MatchResult(
                entity_id=existing.entity_id,
                name=existing_name,
                score=round(score, 1),
                verdict=verdict,
                signals={
                    "name_similarity": round(name_score, 3),
                    "alias_similarity": round(alias_score, 3),
                    "location_similarity": round(location_score, 3),
                    "context_similarity": round(context_score, 3),
                },
            )
        )

    results.sort(key=lambda r: (-r.score, r.name))
    return results[:limit]


def _verdict(score: float) -> str:
    if score >= THRESHOLD_STRONG:
        return MATCH_STRONG
    if score >= THRESHOLD_POSSIBLE:
        return MATCH_POSSIBLE
    return MATCH_KEEP_SEPARATE


def _aliases_of(db: Session, entity: Entity) -> list[str]:
    if entity.entity_type == "PERSON" and entity.person:
        return list(entity.person.aliases or [])
    if entity.entity_type == "ORGANIZATION" and entity.organization:
        return list(entity.organization.aliases or [])
    return []


def _person_location(db: Session, entity: Entity) -> str | None:
    # A person's residence is recorded via RESIDES_IN relationships;
    # for matching we fall back to notes text (documented location hints).
    if entity.person and entity.person.notes:
        match = re.search(r"\b(?:resides in|location:)\s*([A-Za-z ]+)", entity.person.notes)
        if match:
            return match.group(1).strip()
    return None
