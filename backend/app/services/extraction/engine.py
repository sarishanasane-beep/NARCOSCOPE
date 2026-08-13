"""Deterministic extraction pipeline.

DOCUMENT
  -> TEXT EXTRACTION
  -> TEXT CLEANING
  -> SENTENCE SEGMENTATION
  -> DATE DETECTION
  -> CASE NUMBER DETECTION
  -> LOCATION / PERSON / ORGANIZATION DETECTION
  -> EVENT DETECTION
  -> RELATIONSHIP PATTERN DETECTION
  -> CANDIDATE CREATION

Everything produced here is a CANDIDATE. Nothing enters trusted data
without human review. When in doubt, the engine prefers "unknown" over
guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from app.services.extraction.case_numbers import CaseNumberCandidate, extract_case_numbers
from app.services.extraction.dates import DateInfo, extract_dates
from app.services.extraction.entities import (
    EntityCandidate,
    extract_entities,
)
from app.services.extraction.events import EventCandidate, extract_events
from app.services.extraction.relationships import (
    ClaimCandidate,
    FactCandidate,
    RelationshipCandidate,
    extract_claims,
    extract_relationships,
)
from app.services.extraction.resolution import resolve_possible_matches
from app.services.extraction.spans import TextSpan
from app.utils.text import normalize_case_number

# Case label references such as "CASE-001" (name-style) vs official numbers.
_LABEL_RE = re.compile(r"^(?:CASE|FIR|CR|NCB|ED|DRI|CBI)-?\d+$", re.IGNORECASE)
_CASE_NAME_IN_SENTENCE = re.compile(r"\bCase\s+([A-Z0-9-]+)\b")


@dataclass
class CaseCandidate:
    case_number: str | None
    case_name: str | None
    action: str  # "create" | "link"
    existing_case_id: str | None = None
    jurisdiction: str | None = None
    span: TextSpan | None = None
    confidence: float = 0.7
    reason: str = "case reference found in document"
    # Optional case category (e.g. DRUG_TRAFFICKING_INVESTIGATION) —
    # provided only by explicit structured CASE blocks; None for the
    # generic engine.
    category: str | None = None
    # Explicit structured CASE fields: STATUS (ACTIVE_INVESTIGATION, ...)
    # and DESCRIPTION. Never inferred.
    status: str | None = None
    description: str | None = None
    # Authoritative structured identity (v2 format: CASE_ID). Optional;
    # never inferred. Used for deterministic ID-based deduplication.
    structured_id: str | None = None


@dataclass
class ExtractionResult:
    entities: list[EntityCandidate] = field(default_factory=list)
    events: list[EventCandidate] = field(default_factory=list)
    relationships: list[RelationshipCandidate] = field(default_factory=list)
    facts: list[FactCandidate] = field(default_factory=list)
    cases: list[CaseCandidate] = field(default_factory=list)
    claims: list[ClaimCandidate] = field(default_factory=list)
    dates: list[DateInfo] = field(default_factory=list)
    sentences: list[TextSpan] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.entities)
            + len(self.events)
            + len(self.relationships)
            + len(self.facts)
            + len(self.cases)
            + len(self.claims)
        )


CaseMatcher = Callable[[str | None, str | None], tuple[str | None, str]]


def _no_case_match(_number: str | None, _name: str | None) -> tuple[str | None, str]:
    return None, "none"


def segment_sentences(text: str) -> list[TextSpan]:
    """Split text into sentences with character spans."""
    sentences: list[TextSpan] = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ".!?" and not _is_abbreviation(text, i):
            j = i + 1
            while j < n and text[j] in " \t\n":
                j += 1
            if j >= n or text[j].isupper() or text[j].isdigit() or text[j] in "\"'(":
                sentences.append(TextSpan(start=start, end=i + 1, text=text[start : i + 1]))
                start = j
                i = j
                continue
        i += 1
    if start < n:
        sentences.append(TextSpan(start=start, end=n, text=text[start:n]))
    return sentences


_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "vs", "no", "fig", "est", "approx", "dept",
    "inc", "ltd", "co", "st", "jan", "feb", "mar", "apr", "jun", "jul", "aug",
    "sep", "oct", "nov", "dec", "etc",
}


def _is_abbreviation(text: str, index: int) -> bool:
    match = re.search(r"([A-Za-z.]+)\.$", text[: index + 1])
    if not match:
        return False
    token = match.group(1).lower().rstrip(".")
    if len(token) == 1 and token.isalpha():
        return True
    return token in _ABBREVIATIONS


def _inside(sentence: TextSpan, span: TextSpan) -> bool:
    return sentence.start <= span.start and span.end <= sentence.end


def _is_label(token: str) -> bool:
    return bool(_LABEL_RE.match(normalize_case_number(token)))


def _build_case_candidates(
    sentences: list[TextSpan],
    case_numbers: list[CaseNumberCandidate],
    entities: list[EntityCandidate],
    matcher: CaseMatcher,
) -> list[CaseCandidate]:
    per_sentence: dict[int, list[CaseNumberCandidate]] = {}
    for number in case_numbers:
        for idx, sentence in enumerate(sentences):
            if _inside(sentence, number.span):
                per_sentence.setdefault(idx, []).append(number)
                break

    candidates: list[CaseCandidate] = []
    for idx, refs in per_sentence.items():
        sentence = sentences[idx]
        labels = [r for r in refs if _is_label(r.normalized)]
        officials = [r for r in refs if not _is_label(r.normalized)]

        if officials and labels:
            # One case: official number + CASE-XXX label as its name.
            official = officials[0]
            name = _CASE_NAME_IN_SENTENCE.search(sentence.text)
            candidates.append(
                _case_candidate(
                    official.normalized,
                    name.group(1) if name else labels[0].normalized,
                    sentence,
                    entities,
                    matcher,
                )
            )
        elif labels:
            for label in labels:
                candidates.append(
                    _case_candidate(
                        None,
                        label.normalized,
                        sentence,
                        entities,
                        matcher,
                    )
                )
        else:
            for official in officials:
                candidates.append(
                    _case_candidate(
                        official.normalized,
                        None,
                        sentence,
                        entities,
                        matcher,
                    )
                )
    return _dedupe_cases(candidates)


def _case_candidate(
    number: str | None,
    name: str | None,
    sentence: TextSpan,
    entities: list[EntityCandidate],
    matcher: CaseMatcher,
) -> CaseCandidate:
    jurisdiction = next(
        (e.name for e in entities if e.entity_type == "LOCATION" and _inside(sentence, e.span)),
        None,
    )
    existing_id, match_kind = matcher(number, name)
    if match_kind == "exact_number":
        return CaseCandidate(
            case_number=number, case_name=name, action="link", existing_case_id=existing_id,
            jurisdiction=jurisdiction, span=sentence,
            reason="official case number matches an existing case",
        )
    if match_kind == "possible_name":
        return CaseCandidate(
            case_number=number, case_name=name, action="link", existing_case_id=existing_id,
            jurisdiction=jurisdiction, span=sentence,
            reason="possible case name match — requires human confirmation",
        )
    return CaseCandidate(
        case_number=number, case_name=name, action="create",
        jurisdiction=jurisdiction, span=sentence,
        reason="new case reference found in document",
    )


def _dedupe_cases(candidates: list[CaseCandidate]) -> list[CaseCandidate]:
    """Merge references to the same case by name, preferring numbered refs."""
    by_name: dict[str, CaseCandidate] = {}
    by_number: dict[str, CaseCandidate] = {}
    for candidate in candidates:
        if candidate.case_name:
            existing = by_name.get(candidate.case_name)
            if existing is None:
                by_name[candidate.case_name] = candidate
            elif existing.case_number is None and candidate.case_number:
                by_name[candidate.case_name] = candidate
        elif candidate.case_number:
            by_number.setdefault(candidate.case_number, candidate)
    return list(by_name.values()) + list(by_number.values())


def run_extraction(
    text: str,
    *,
    case_matcher: CaseMatcher | None = None,
) -> ExtractionResult:
    matcher = case_matcher or _no_case_match
    sentences = segment_sentences(text)
    dates = extract_dates(text)
    case_numbers = extract_case_numbers(text)
    entities = extract_entities(text, sentences)
    events = extract_events(text, sentences, entities, dates, case_numbers)
    relationships, facts = extract_relationships(text, sentences, entities)
    # Entity resolution: distinct-but-similar person forms become
    # POSSIBLE_MATCH candidates (human confirmation required) — they are
    # never merged automatically.
    relationships = relationships + resolve_possible_matches(entities, sentences)
    claims = extract_claims(sentences, entities)
    cases = _build_case_candidates(sentences, case_numbers, entities, matcher)

    return ExtractionResult(
        entities=entities,
        events=events,
        relationships=relationships,
        facts=facts,
        cases=cases,
        claims=claims,
        dates=dates,
        sentences=sentences,
    )


def evidence_span_for(candidate_span: TextSpan, sentences: list[TextSpan]) -> TextSpan:
    """The sentence containing a span (context evidence), or the span itself."""
    for sentence in sentences:
        if _inside(sentence, candidate_span) and len(sentence.text) > len(candidate_span.text):
            return sentence
    return candidate_span
