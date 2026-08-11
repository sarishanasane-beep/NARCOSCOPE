"""Deterministic entity resolution — possible matches between candidates.

After extraction, person forms that may refer to the same individual
(e.g. ``S. Patil`` and ``Suresh Patil``) are NEVER merged automatically.
Instead a ``POSSIBLE_MATCH`` relationship candidate is created with a
confidence score and evidence; a human must confirm it before any
canonical merge. Exact duplicate normalized names are already
deduplicated by the entity extractor, so only distinct-but-similar forms
reach this layer.
"""

from __future__ import annotations

from app.services.extraction.entities import ENTITY_TYPE_PERSON, EntityCandidate, forms_alias
from app.services.extraction.relationships import RelationshipCandidate
from app.services.extraction.spans import TextSpan
from app.utils.text import normalize_name

POSSIBLE_MATCH_CONFIDENCE = 0.6


def _span_for_entity(entity: EntityCandidate, sentences: list[TextSpan]) -> TextSpan:
    """The sentence containing the entity (context evidence), or the span itself."""
    for sentence in sentences:
        if sentence.start <= entity.span.start and entity.span.end <= sentence.end:
            return sentence
    return entity.span


def _order_names(
    a_name: str, a_tokens: list[str], b_name: str, b_tokens: list[str]
) -> tuple[str, str]:
    """Return ``(full, variant)`` — the fuller/canonical form first.

    The initial form (single-letter first token) is always the variant,
    then the shorter token list. This keeps the direction
    "Suresh Patil POSSIBLE_MATCH S. Patil" regardless of which side is
    the newly extracted one.
    """
    a_initial = len(a_tokens) >= 2 and len(a_tokens[0]) == 1
    b_initial = len(b_tokens) >= 2 and len(b_tokens[0]) == 1
    if b_initial and not a_initial:
        return a_name, b_name
    if a_initial and not b_initial:
        return b_name, a_name
    if len(b_tokens) < len(a_tokens):
        return a_name, b_name
    return b_name, a_name


def resolve_possible_matches(
    entities: list[EntityCandidate],
    sentences: list[TextSpan],
) -> list[RelationshipCandidate]:
    """Create ``POSSIBLE_MATCH`` candidates for distinct-but-similar persons.

    Only same-type person candidates are compared, and only pairs that
    share a documented name form (initial forms, strict subsets) produce
    a candidate. Ambiguity is preserved: a variant that could match
    several full names yields one candidate per pair.
    """
    persons = [e for e in entities if e.entity_type == ENTITY_TYPE_PERSON]
    matches: list[RelationshipCandidate] = []
    seen: set[tuple[str, str]] = set()

    for i, left in enumerate(persons):
        for right in persons[i + 1 :]:
            left_tokens = left.normalized_name.split()
            right_tokens = right.normalized_name.split()
            if not forms_alias(left_tokens, right_tokens):
                continue
            key = (left.normalized_name, right.normalized_name)
            if key in seen:
                continue
            seen.add(key)

            # Order the pair: full form first, variant second (initial
            # forms and shorter names are the variant).
            full_name, variant_name = _order_names(
                left.name, left_tokens, right.name, right_tokens
            )
            full = left if left.name == full_name else right
            variant = right if full is left else left

            matches.append(
                RelationshipCandidate(
                    source_name=full.name,
                    source_type=full.entity_type,
                    relationship_type="POSSIBLE_MATCH",
                    target_name=variant.name,
                    target_type=variant.entity_type,
                    span=_span_for_entity(variant, sentences),
                    confidence=POSSIBLE_MATCH_CONFIDENCE,
                    reason=(
                        f"Possible entity match: \"{full.name}\" and \"{variant.name}\" "
                        "may refer to the same person. Human confirmation is required "
                        "before any canonical merge."
                    ),
                    classification="CANDIDATE",
                )
            )
    return matches


def possible_match_against_existing(
    new_entities: list[EntityCandidate],
    existing_names: set[str],
    existing_pairs: set[tuple[str, str]],
) -> list[RelationshipCandidate]:
    """Create ``POSSIBLE_MATCH`` candidates for newly extracted persons
    against known persons already stored in the database.

    Runs at persistence time (across documents). Exact canonical names
    are already deduplicated by the candidate merge and same-sentence
    aliases by the alias mechanism — this layer only links
    distinct-but-similar forms (initial forms, strict subsets). One
    candidate per pair, ordered full-form -> variant, classification
    CANDIDATE, human confirmation required. Never merges automatically.
    """
    persons = [e for e in new_entities if e.entity_type == ENTITY_TYPE_PERSON]
    matches: list[RelationshipCandidate] = []
    for entity in persons:
        entity_tokens = entity.normalized_name.split()
        for existing_name in sorted(existing_names):
            existing_tokens = normalize_name(existing_name).split()
            if existing_tokens == entity_tokens:
                continue
            if not forms_alias(entity_tokens, existing_tokens):
                continue
            full_name, variant_name = _order_names(
                entity.name, entity_tokens, existing_name, existing_tokens
            )
            key = (normalize_name(full_name), normalize_name(variant_name))
            if key in existing_pairs:
                continue
            matches.append(
                RelationshipCandidate(
                    source_name=full_name,
                    source_type=ENTITY_TYPE_PERSON,
                    relationship_type="POSSIBLE_MATCH",
                    target_name=variant_name,
                    target_type=ENTITY_TYPE_PERSON,
                    span=entity.span,
                    confidence=POSSIBLE_MATCH_CONFIDENCE,
                    reason=(
                        f"Possible entity match: \"{full_name}\" and \"{variant_name}\" "
                        "may refer to the same person. Human confirmation is required "
                        "before any canonical merge."
                    ),
                    classification="CANDIDATE",
                )
            )
    return matches
