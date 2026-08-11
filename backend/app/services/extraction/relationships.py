"""Conservative relationship / fact / claim extraction.

Relationships are ONLY created when a meaningful linguistic pattern
exists (arrested during, took place in, resides in, located in,
operates in, was seen with, ...). Co-occurrence in a paragraph is NEVER
enough. Endpoints are cross-checked against detected entities so we
never invent links.

Multi-source sentences ("Rahul Patel and Zubin Irani were arrested
during Operation Redline") and ``also`` modifiers are handled by
extracting the clause prefix before the verb.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.extraction.dictionaries import CLAIM_STATUS_KEYWORDS
from app.services.extraction.entities import (
    ENTITY_TYPE_LOCATION,
    ENTITY_TYPE_ORGANIZATION,
    ENTITY_TYPE_OTHER,
    ENTITY_TYPE_PERSON,
    EntityCandidate,
)
from app.services.extraction.spans import TextSpan
from app.utils.text import normalize_name, strip_titles

LOCATION_NAME = r"([A-Z][a-z]+(?:[\s-][A-Z][a-z]+){0,2})"
PERSON_NAME = r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
OP_NAME = r"(Operation\s+[A-Z][A-Za-z0-9]+)"
CASE_REF = r"(Case\s+[A-Z0-9-]+)"

# relationship_type -> (verb pattern with ONE capture group, target kind)
_PATTERNS: list[tuple[str, str, str]] = [
    ("ARRESTED_IN", r"\s(?:was|were)\s+(?:also\s+)?arrested\s+(?:during|in)\s+(?:the\s+)?" + OP_NAME, "entity"),
    ("PARTICIPATED_IN", r"\s+(?:also\s+)?participated\s+in\s+(?:the\s+)?" + OP_NAME, "entity"),
    ("PARTICIPATED_IN", r"\s+led\s+" + OP_NAME, "entity"),
    ("OCCURRED_IN", r"\s+(?:took\s+place|occurred|was\s+conducted|was\s+carried\s+out|was\s+launched)\s+in\s+" + LOCATION_NAME, "entity"),
    ("RESIDES_IN", r"\s+(?:also\s+)?resides?\s+in\s+" + LOCATION_NAME, "entity"),
    ("LOCATED_IN", r"\s+(?:is|was)\s+(?:also\s+)?located\s+in\s+" + LOCATION_NAME, "entity"),
    ("OPERATES", r"\s+(?:also\s+)?operates\s+in\s+" + LOCATION_NAME, "entity"),
    ("ASSOCIATED_WITH", r"\s+was\s+seen\s+with\s+" + PERSON_NAME, "person"),
]

_FACT_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "INVOLVED_IN",
        re.compile(rf"{PERSON_NAME}\s+was\s+involved\s+in\s+(?:the\s+)?{CASE_REF}", re.IGNORECASE),
    ),
    (
        "QUESTIONED_IN",
        re.compile(rf"{PERSON_NAME}\s+was\s+questioned\s+in\s+connection\s+with\s+(?:the\s+)?{CASE_REF}", re.IGNORECASE),
    ),
    (
        "MENTIONED_IN",
        re.compile(rf"{PERSON_NAME}\s+(?:was\s+mentioned\s+in|is\s+named\s+in)\s+{CASE_REF}(?:\s+and\s+{CASE_REF})?", re.IGNORECASE),
    ),
    (
        "INVOLVED_IN",
        re.compile(rf"in\s+which\s+{PERSON_NAME}\s+is\s+involved", re.IGNORECASE),
    ),
]

_CLAIM_RE = re.compile(
    "|".join(re.escape(kw) for kw in sorted(CLAIM_STATUS_KEYWORDS, key=len, reverse=True)),
    re.IGNORECASE,
)

_LAST_NAME_SEQUENCE = re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*$")


@dataclass
class RelationshipCandidate:
    source_name: str
    source_type: str
    relationship_type: str
    target_name: str
    target_type: str
    span: TextSpan
    confidence: float
    reason: str
    classification: str = "DIRECT"
    extra: dict = field(default_factory=dict)


@dataclass
class FactCandidate:
    subject_name: str
    subject_type: str
    predicate: str
    object_name: str | None
    object_type: str | None
    span: TextSpan
    confidence: float
    reason: str
    case_ref: str | None = None
    event_ref: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ClaimCandidate:
    claim_text: str
    claim_status: str
    subject_name: str | None
    span: TextSpan
    confidence: float


def _entity_by_name(entities: list[EntityCandidate], name: str) -> EntityCandidate | None:
    normalized = normalize_name(name)
    for entity in entities:
        if entity.normalized_name == normalized:
            return entity
    return None


def _inside(sentence: TextSpan, span: TextSpan) -> bool:
    return sentence.start <= span.start and span.end <= sentence.end


def _clean_source(chunk: str) -> str:
    chunk = chunk.strip()
    chunk = re.sub(r"\s+(?:also|and|,)+$", "", chunk).strip()
    chunk = re.sub(r"^(?:the|a|an)\s+", "", chunk, flags=re.IGNORECASE).strip()
    chunk = re.sub(r"[,.;:]+$", "", chunk).strip()
    return chunk


def _resolve_source(entities: list[EntityCandidate], chunk: str) -> EntityCandidate | None:
    """Try the full cleaned chunk, then the title-stripped form, then the
    trailing name sequence."""
    cleaned = _clean_source(chunk)
    entity = _entity_by_name(entities, cleaned)
    if entity is not None:
        return entity
    stripped = strip_titles(cleaned)
    if stripped and stripped != cleaned:
        entity = _entity_by_name(entities, stripped)
        if entity is not None:
            return entity
    match = _LAST_NAME_SEQUENCE.search(stripped or cleaned)
    if match:
        return _entity_by_name(entities, match.group(1))
    return None


def extract_relationships(
    text: str,
    sentences: list[TextSpan],
    entities: list[EntityCandidate],
) -> tuple[list[RelationshipCandidate], list[FactCandidate]]:
    relationships: list[RelationshipCandidate] = []
    facts: list[FactCandidate] = []
    seen_rel: set[tuple[str, str, str]] = set()
    seen_fact: set[tuple[str, str, str]] = set()

    for sentence in sentences:
        for relationship_type, verb_pattern, target_kind in _PATTERNS:
            regex = re.compile(verb_pattern, re.IGNORECASE)
            for match in regex.finditer(sentence.text):
                rel_span = TextSpan(
                    start=sentence.start + match.start(),
                    end=sentence.start + match.end(),
                    text=match.group(0),
                )
                target_name = _clean_source(match.group(1))
                target_entity = _entity_by_name(entities, target_name)
                if target_entity is None:
                    continue
                target_type = target_entity.entity_type

                prefix = sentence.text[: match.start()]
                if relationship_type in ("ARRESTED_IN", "PARTICIPATED_IN"):
                    source_chunks = re.split(r"\s+and\s+|\s*,\s*", prefix)
                else:
                    source_chunks = [prefix]

                for chunk in source_chunks:
                    if not chunk.strip():
                        continue
                    source_entity = _resolve_source(entities, chunk)
                    if source_entity is None:
                        continue
                    key = (relationship_type, source_entity.normalized_name, target_entity.normalized_name)
                    if key in seen_rel:
                        continue
                    seen_rel.add(key)
                    confidence = 0.55 if relationship_type == "ASSOCIATED_WITH" else 0.7
                    relationships.append(
                        RelationshipCandidate(
                            source_name=source_entity.name,
                            source_type=source_entity.entity_type,
                            relationship_type=relationship_type,
                            target_name=target_entity.name,
                            target_type=target_type,
                            span=rel_span,
                            confidence=confidence,
                            reason=f"relationship pattern: {relationship_type}",
                        )
                    )

        # Case-targeted facts
        for predicate, pattern in _FACT_PATTERNS:
            for match in pattern.finditer(sentence.text):
                fact_span = TextSpan(
                    start=sentence.start + match.start(),
                    end=sentence.start + match.end(),
                    text=match.group(0),
                )
                subject_entity = _resolve_source(entities, match.group(1))
                if subject_entity is None:
                    continue
                if predicate == "MENTIONED_IN":
                    case_refs = [g for g in match.groups()[1:] if g]
                else:
                    case_refs = []
                if not case_refs:
                    found = re.search(r"Case\s+[A-Z0-9-]+", sentence.text)
                    if found:
                        case_refs = [found.group(0)]
                for case_ref in case_refs:
                    key = (predicate, subject_entity.normalized_name, case_ref)
                    if key in seen_fact:
                        continue
                    seen_fact.add(key)
                    facts.append(
                        FactCandidate(
                            subject_name=subject_entity.name,
                            subject_type=subject_entity.entity_type,
                            predicate=predicate,
                            object_name=case_ref,
                            object_type="CASE",
                            span=fact_span,
                            confidence=0.7,
                            reason=f"fact pattern: {predicate}",
                            case_ref=case_ref,
                        )
                    )

    return relationships, facts


def extract_claims(
    sentences: list[TextSpan],
    entities: list[EntityCandidate],
) -> list[ClaimCandidate]:
    claims: list[ClaimCandidate] = []
    for sentence in sentences:
        match = _CLAIM_RE.search(sentence.text)
        if not match:
            continue
        keyword = match.group(0).lower()
        status = next(
            (v for k, v in CLAIM_STATUS_KEYWORDS.items() if k in keyword),
            "UNKNOWN",
        )
        subject = next(
            (e.name for e in entities if e.entity_type == ENTITY_TYPE_PERSON and _inside(sentence, e.span)),
            None,
        )
        claims.append(
            ClaimCandidate(
                claim_text=sentence.text.strip(),
                claim_status=status,
                subject_name=subject,
                span=sentence,
                confidence=0.7,
            )
        )
    return claims
