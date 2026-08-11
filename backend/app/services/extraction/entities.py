"""Deterministic entity extraction.

Combines controlled dictionaries (locations, known organizations),
regex patterns (operations, acronyms, initials) and conservative
contextual rules for people. No NLP model is required.

Extracted entities are CANDIDATES: they are never auto-confirmed and
never merged with existing entities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.extraction.dictionaries import (
    LOCATIONS,
    NAME_STOPWORDS,
    ORGANIZATIONS,
    ORG_SUFFIXES,
    PERSON_CONTEXT_WORDS,
    PERSON_TITLE_PREFIXES,
    SENTENCE_START_STOPWORDS,
)
from app.services.extraction.spans import TextSpan
from app.utils.text import normalize_name, strip_titles

ENTITY_TYPE_LOCATION = "LOCATION"
ENTITY_TYPE_ORGANIZATION = "ORGANIZATION"
ENTITY_TYPE_PERSON = "PERSON"
ENTITY_TYPE_OTHER = "OTHER"

_LOCATION_LOWER = {name.lower(): name for name in LOCATIONS}
_ORG_LOWER = {name.lower(): name for name in ORGANIZATIONS}

_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
_OPERATION_RE = re.compile(r"\bOperation\s+([A-Z][A-Za-z0-9]+)\b")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}(?![A-Za-z0-9-])")
_NAME_SEQUENCE_RE = re.compile(
    r"\b[A-Z][a-z]{1,}(?:['-][A-Za-z]+)?(?:\s+[A-Z][a-z]{1,}(?:['-][A-Za-z]+)?){0,3}\b"
)
_INITIALS_RE = re.compile(r"\b[A-Z]\.\s*[A-Z][a-z]{2,}\b")
_DIGIT_AFTER = re.compile(r"^\s*\d")
_WORD_AFTER = re.compile(r"[A-Za-z]+")

# Head words that begin a multi-part organization name. Combined with the
# connector pattern below they capture names the controlled dictionary
# does not contain (e.g. "Directorate General of GST Intelligence").
_ORG_HEAD = (
    r"Directorate|Department|Bureau|Agency|Commission|Ministry|Office|Authority|"
    r"Force|Corporation|Board|Council|Institute|Institution|Administration|Customs|"
    r"Excise|Bank|Cell|Unit|Division|Police|Foundation|Trust|Society|Group|"
    r"Industries|Enterprises|Traders|Imports|Exports|Company"
)
# "X (General) of Y Z" organization names. Only "of"/"for" connectors are
# used so two distinct organizations joined by "and" are never merged.
_ORG_OF_NAME_RE = re.compile(
    rf"\b(?:{_ORG_HEAD})"
    rf"(?:\s+[A-Z][A-Za-z0-9]+)?"
    rf"(?:\s+(?:of|for)\s+[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*){{1,3}}"
)

# Placeholder organization forms such as "Organization X".
_PLACEHOLDER_ORG_RE = re.compile(r"^(?:Organization|Agency|Company|Firm|Group|Entity)\s+[A-Z0-9][A-Za-z0-9]*$")
# Text-level placeholder pattern: the capitalized-name-sequence rule cannot
# span a single letter ("Organization X" — "X" has no lowercase), so this
# pass captures the full span directly.
_PLACEHOLDER_ORG_TEXT_RE = re.compile(
    r"\b(?:Organization|Agency|Company|Firm|Group|Entity)\s+[A-Z0-9][A-Za-z0-9]*\b"
)

# Organization labels: "Organization profile: Blue Horizon Imports.",
# "Company: Acme Ltd", "Agency: X". The word before the colon is a
# contextual label, not the entity name — the entity is the captured name
# after the colon, and the label word itself must not become a separate
# organization candidate. Requires a colon, so "Organization X" (no
# colon) and standalone uses ("The Directorate issued a notice.") are
# untouched.
_ORG_LABEL_RE = re.compile(
    r"\b(?:Organization|Agency|Company|Firm|Group|Entity)\s*(?:profile|name)?\s*:\s*"
    r"([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]+)*)"
)

# Common capitalized non-person nouns/adverbs that must never be classified
# as people even when a verb follows ("Officially stated ..."). This is a
# curated set applied only inside the person branch — words that are
# legitimate organizations (Directorate, Bureau, Department) are classified
# as ORGANIZATION before this check and never reach it.
NON_PERSON_NAMES: set[str] = {
    "officially", "reportedly", "allegedly", "organization", "department",
    "directorate", "bureau", "investigation", "operation", "official",
    "officials", "hearing", "court", "records", "documents", "evidence",
    "statement", "report", "case", "fir", "registration", "search", "raid",
    "seizure", "arrest", "interception", "proceeding", "proceedings", "trial",
    "consignment", "substances", "materials", "communications", "next",
    "following", "further", "moreover", "meanwhile", "however", "also",
}

# Structural patterns for labels that are never person names ("Case No",
# "Case Number", "Case Bluewater").
_NUMBER_TAIL_RE = re.compile(r"\s(?:no\.?|number)$", re.IGNORECASE)
_CASE_LABEL_RE = re.compile(r"^case\s+", re.IGNORECASE)


def _is_non_person_phrase(name: str) -> bool:
    """Structural rejection: shapes that are never person names.

    Combines a curated non-person word set with structural patterns
    (labels ending in "No"/"Number", "Case X" references). A generic
    word can still be an organization elsewhere ("The Directorate
    issued a notice.") because this check only runs in the person
    branch after organization classification.
    """
    lower = name.lower()
    if lower in NON_PERSON_NAMES:
        return True
    if _NUMBER_TAIL_RE.search(name):
        return True
    if _CASE_LABEL_RE.match(lower) and len(name.split()) >= 2:
        return True
    return False


@dataclass
class EntityCandidate:
    name: str
    entity_type: str
    span: TextSpan
    confidence: float
    reason: str
    aliases: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)


def _span(text: str, match: re.Match) -> TextSpan:
    return TextSpan(start=match.start(), end=match.end(), text=match.group(0))


def _is_sentence_start(sentences: list[TextSpan], offset: int) -> bool:
    return any(sentence.start == offset for sentence in sentences)


def _next_words(text: str, offset: int, count: int = 4) -> list[str]:
    rest = text[offset:]
    words = _WORD_AFTER.findall(rest)
    return [w.lower() for w in words[:count]]


def _line_start(text: str, offset: int) -> str:
    line_start = text.rfind("\n", 0, offset) + 1
    return text[line_start : offset + 20]


def _classified_sequence(
    text: str,
    match: re.Match,
    sentences: list[TextSpan],
) -> EntityCandidate | None:
    raw = match.group(0)
    name = _ARTICLE_RE.sub("", raw).strip()
    if not name:
        return None
    first_token = name.split()[0].lower().rstrip(".")
    if first_token in NAME_STOPWORDS:
        return None

    start = match.start() + (len(raw) - len(name))
    span = TextSpan(start=start, end=start + len(name), text=name)
    sentence_start = _is_sentence_start(sentences, start)
    next_words = _next_words(text, span.end)

    # 1. Named operations -> OTHER entities (targets for relationships).
    op_match = _OPERATION_RE.match(name)
    if op_match:
        return EntityCandidate(
            name=name, entity_type=ENTITY_TYPE_OTHER, span=span,
            confidence=0.85, reason="operation name pattern",
        )

    # 2. Location dictionary.
    if name.lower() in _LOCATION_LOWER:
        return EntityCandidate(
            name=_LOCATION_LOWER[name.lower()], entity_type=ENTITY_TYPE_LOCATION, span=span,
            confidence=0.9, reason="dictionary location match",
        )

    # 3. Organizations (suffix pattern or dictionary).
    last_token = name.split()[-1].lower()
    if last_token in {s.lower() for s in ORG_SUFFIXES} or name.lower() in _ORG_LOWER:
        confidence = 0.9 if name.lower() in _ORG_LOWER else 0.8
        return EntityCandidate(
            name=name, entity_type=ENTITY_TYPE_ORGANIZATION, span=span,
            confidence=confidence, reason="organization pattern",
            extra={"organization_type": _guess_org_type(name)},
        )

    # 3b. Placeholder organization forms: "Organization X", "Agency Y".
    if _PLACEHOLDER_ORG_RE.match(name):
        return EntityCandidate(
            name=name, entity_type=ENTITY_TYPE_ORGANIZATION, span=span,
            confidence=0.8, reason="placeholder organization pattern",
        )

    # 4. People.
    if _is_non_person_phrase(name):
        return None
    stripped = strip_titles(name)
    # A title was actually stripped when the remaining name differs — the
    # canonical name is the person's name WITHOUT the title ("Inspector
    # Suresh Patil" -> "Suresh Patil"), with the titled form kept as an
    # alias.
    has_title = bool(stripped) and stripped != name
    has_context = bool(next_words) and (
        next_words[0] in PERSON_CONTEXT_WORDS
        or (
            next_words[0] in {"and", "or", "with"}
            and any(w in PERSON_CONTEXT_WORDS for w in next_words[1:4])
        )
    )
    multi_token = len(name.split()) >= 2
    mid_sentence = not sentence_start

    # Exclude sentence-start capitalized sequences whose first token is a
    # common sentence-start word (Police, Authorities, The, ...).
    if sentence_start and first_token in SENTENCE_START_STOPWORDS:
        return None

    if has_title:
        canonical = strip_titles(name)
        alias = name if canonical != name else None
        return EntityCandidate(
            name=canonical, entity_type=ENTITY_TYPE_PERSON, span=span,
            confidence=0.9, reason="person title prefix",
            aliases=[alias] if alias else [],
        )
    if has_context:
        return EntityCandidate(
            name=name, entity_type=ENTITY_TYPE_PERSON, span=span,
            confidence=0.8, reason="person verb context",
        )
    if multi_token and mid_sentence:
        return EntityCandidate(
            name=name, entity_type=ENTITY_TYPE_PERSON, span=span,
            confidence=0.5, reason="capitalized name sequence (low confidence)",
        )
    return None


def _guess_org_type(name: str) -> str:
    lower = name.lower()
    if any(k in lower for k in ("police", "bureau", "agency", "department", "directorate", "customs", "excise", "force", "cell", "unit", "division", "task force")):
        return "AGENCY"
    if "court" in lower:
        return "COURT"
    if any(k in lower for k in ("ltd", "inc", "company", "corporation", "imports", "exports", "traders", "enterprises", "industries")):
        return "COMPANY"
    return "ORGANIZATION"


def _acronym_candidate(text: str, match: re.Match) -> EntityCandidate | None:
    token = match.group(0)
    if token not in ORGANIZATIONS:
        return None
    if _DIGIT_AFTER.match(text[match.end() :]):
        return None  # e.g. "FIR 456/2026" — label, not an organization
    if _line_start(text, match.start()).startswith("DEMO DATA"):
        return None
    return EntityCandidate(
        name=token, entity_type=ENTITY_TYPE_ORGANIZATION, span=_span(text, match),
        confidence=0.9, reason="known organization acronym",
        extra={"organization_type": "AGENCY"},
    )


def _initial_candidate(text: str, match: re.Match) -> EntityCandidate | None:
    token = match.group(0)
    return EntityCandidate(
        name=token, entity_type=ENTITY_TYPE_PERSON, span=_span(text, match),
        confidence=0.6, reason="initial-form person name",
    )


def forms_alias(candidate_tokens: list[str], existing_tokens: list[str]) -> bool:
    """True when one name is a documented form of the other.

    Handles strict subsets (``Sunil Kulkarni`` vs ``Kulkarni``) and
    initial forms (``S. Kulkarni`` vs ``Sunil Kulkarni``). Only produces
    candidate aliases within one sentence — it never merges identities.
    """
    if not candidate_tokens or not existing_tokens:
        return False
    if candidate_tokens != existing_tokens and (
        set(candidate_tokens) <= set(existing_tokens)
        or set(existing_tokens) <= set(candidate_tokens)
    ):
        return True
    # Initial form: "S. Kulkarni" ~ "Sunil Kulkarni" (first name starts
    # with the initial and the surname matches).
    if len(candidate_tokens) >= 2 and len(candidate_tokens[0]) == 1:
        return (
            candidate_tokens[-1] in existing_tokens
            and existing_tokens[0].startswith(candidate_tokens[0])
        )
    if len(existing_tokens) >= 2 and len(existing_tokens[0]) == 1:
        return (
            existing_tokens[-1] in candidate_tokens
            and candidate_tokens[0].startswith(existing_tokens[0])
        )
    return False


def _merge_alias_forms(
    candidates: list[EntityCandidate], sentences: list[TextSpan]
) -> list[EntityCandidate]:
    """Turn initial/partial forms into aliases of the full name.

    Within the same sentence, "S. Kulkarni" becomes an alias of
    "Sameer Kulkarni" instead of a separate person candidate. A form is
    only folded into an alias when exactly one candidate in that
    sentence matches, so uncertain identities stay separate.
    """
    merged: list[EntityCandidate] = []
    for candidate in candidates:
        if candidate.entity_type != ENTITY_TYPE_PERSON:
            merged.append(candidate)
            continue
        tokens = candidate.normalized_name.split()
        sentence = next((s for s in sentences if _span_inside(s, candidate.span)), None)
        matches: list[EntityCandidate] = []
        for existing in merged:
            if existing.entity_type != ENTITY_TYPE_PERSON:
                continue
            existing_sentence = next((s for s in sentences if _span_inside(s, existing.span)), None)
            if sentence is None or existing_sentence is None or sentence != existing_sentence:
                continue
            if forms_alias(tokens, existing.normalized_name.split()):
                matches.append(existing)
        if len(matches) == 1 and candidate.name not in matches[0].aliases:
            matches[0].aliases.append(candidate.name)
        else:
            merged.append(candidate)
    return merged


def _span_inside(sentence: TextSpan, span: TextSpan) -> bool:
    return sentence.start <= span.start and span.end <= sentence.end


def _dict_pattern(canonical: str) -> str:
    """Whitespace-tolerant dictionary pattern.

    Word separators are ``\s+`` (not literal spaces) so a full name still
    matches when PDF/DOCX extraction inserts a line break inside it
    (e.g. "Directorate of Revenue\nIntelligence"). Without this the full
    organization would be missed and only the fragments would survive.
    """
    return rf"(?<![A-Za-z])" + r"\s+".join(re.escape(w) for w in canonical.split()) + rf"(?![A-Za-z])"


def extract_entities(text: str, sentences: list[TextSpan]) -> list[EntityCandidate]:
    candidates: list[EntityCandidate] = []

    # Locations from the controlled dictionary (multi-word safe).
    for canonical in sorted(_LOCATION_LOWER.values(), key=len, reverse=True):
        pattern = _dict_pattern(canonical)
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidates.append(
                EntityCandidate(
                    name=canonical, entity_type=ENTITY_TYPE_LOCATION, span=_span(text, match),
                    confidence=0.9, reason="dictionary location match",
                )
            )

    # Organizations from the controlled dictionary (handles "of" in names
    # such as "Directorate of Revenue Intelligence").
    for canonical in sorted(_ORG_LOWER.values(), key=len, reverse=True):
        pattern = _dict_pattern(canonical)
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidates.append(
                EntityCandidate(
                    name=canonical, entity_type=ENTITY_TYPE_ORGANIZATION, span=_span(text, match),
                    confidence=0.9, reason="dictionary organization match",
                    extra={"organization_type": _guess_org_type(canonical)},
                )
            )

    # Named operations -> OTHER entities.
    for match in _OPERATION_RE.finditer(text):
        name = match.group(0)
        candidates.append(
            EntityCandidate(
                name=name, entity_type=ENTITY_TYPE_OTHER, span=_span(text, match),
                confidence=0.85, reason="operation name pattern",
            )
        )

    # Known acronyms.
    for match in _ACRONYM_RE.finditer(text):
        candidate = _acronym_candidate(text, match)
        if candidate:
            candidates.append(candidate)

    # Capitalized name sequences.
    for match in _NAME_SEQUENCE_RE.finditer(text):
        candidate = _classified_sequence(text, match, sentences)
        if candidate:
            candidates.append(candidate)

    # Initial-form names (S. Kulkarni).
    for match in _INITIALS_RE.finditer(text):
        candidate = _initial_candidate(text, match)
        if candidate:
            candidates.append(candidate)

    # Multi-part organization names ("X of Y") not in the dictionary.
    for match in _ORG_OF_NAME_RE.finditer(text):
        name = match.group(0)
        candidates.append(
            EntityCandidate(
                name=name, entity_type=ENTITY_TYPE_ORGANIZATION, span=_span(text, match),
                confidence=0.85, reason="multi-part organization name pattern",
            )
        )

    # Placeholder organization forms: "Organization X", "Agency Y".
    for match in _PLACEHOLDER_ORG_TEXT_RE.finditer(text):
        name = match.group(0)
        candidates.append(
            EntityCandidate(
                name=name, entity_type=ENTITY_TYPE_ORGANIZATION, span=_span(text, match),
                confidence=0.8, reason="placeholder organization pattern",
            )
        )

    # Organization labels: "Organization profile: Blue Horizon Imports."
    # The label word ("Organization") is contextual — the entity is the
    # name after the colon, and the label word must not become an
    # organization of its own.
    label_spans: list[TextSpan] = []
    for match in _ORG_LABEL_RE.finditer(text):
        name = match.group(1)
        candidates.append(
            EntityCandidate(
                name=name, entity_type=ENTITY_TYPE_ORGANIZATION,
                span=TextSpan(start=match.start(1), end=match.end(1), text=name),
                confidence=0.9, reason="organization label pattern",
                extra={"organization_type": _guess_org_type(name)},
            )
        )
        # The suppression span is only the label prefix (label word +
        # optional "profile"/"name" + colon) — NOT the captured name.
        # Ending at match.end(1) (the end of the name) would drop the
        # organization candidate itself.
        label_spans.append(
            TextSpan(start=match.start(), end=match.start(1), text=text[match.start() : match.start(1)])
        )
    candidates = _drop_label_word_candidates(candidates, label_spans)

    # Prefer the longest/highest-specificity span for overlapping
    # organization candidates (e.g. "Directorate of Revenue Intelligence"
    # over the fragment "Directorate").
    candidates = _drop_fragments_inside_organizations(candidates)
    _capture_parent_locations(text, candidates)
    candidates = _merge_alias_forms(candidates, sentences)
    return _dedupe(candidates)


def _drop_label_word_candidates(
    candidates: list[EntityCandidate], label_spans: list[TextSpan]
) -> list[EntityCandidate]:
    """Suppress a label word that introduces a named organization.

    In "Organization profile: Blue Horizon Imports." the word
    "Organization" is a contextual label, not an entity — the entity is
    the name after the colon. Standalone uses without a colon ("The
    Directorate issued a notice.", "Organization X") are untouched.
    """
    if not label_spans:
        return candidates
    kept: list[EntityCandidate] = []
    for candidate in candidates:
        if candidate.entity_type in (ENTITY_TYPE_ORGANIZATION, ENTITY_TYPE_PERSON) and any(
            label.start <= candidate.span.start and candidate.span.end <= label.end
            for label in label_spans
        ):
            continue
        kept.append(candidate)
    return kept


def _drop_fragments_inside_organizations(
    candidates: list[EntityCandidate],
) -> list[EntityCandidate]:
    """Drop generic fragments fully contained in a longer organization span.

    When the text explicitly contains a specific organization name, the
    full name wins: "Directorate of Revenue Intelligence" must not also
    produce a bare "Directorate" (or "Customs" beside "Customs
    Department"). Person-shaped fragments that are clearly part of an
    organization name ("Revenue Intelligence") are dropped too. Location
    and operation candidates are never dropped here, and a generic word
    that stands alone ("The Directorate issued a notice.") is kept.
    """
    orgs = [c for c in candidates if c.entity_type == ENTITY_TYPE_ORGANIZATION]
    kept: list[EntityCandidate] = []
    for candidate in candidates:
        if candidate.entity_type not in (ENTITY_TYPE_ORGANIZATION, ENTITY_TYPE_PERSON):
            kept.append(candidate)
            continue
        inside_org = any(
            other.span.start <= candidate.span.start
            and candidate.span.end <= other.span.end
            and other.span.length > candidate.span.length
            for other in orgs
        )
        if not inside_org:
            kept.append(candidate)
    return kept


def _capture_parent_locations(text: str, candidates: list[EntityCandidate]) -> None:
    """Attach parent locations for "X, Y" pairs (e.g. Pune, Maharashtra)."""
    for candidate in candidates:
        if candidate.entity_type != ENTITY_TYPE_LOCATION:
            continue
        rest = text[candidate.span.end :]
        match = re.match(r"^\s*,\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", rest)
        if not match:
            continue
        parent = match.group(1)
        if parent.lower() in _LOCATION_LOWER:
            candidate.extra["parent_location"] = _LOCATION_LOWER[parent.lower()]


def _dedupe(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    """Keep one candidate per (entity_type, normalized name), merging extras.

    Every occurrence span is preserved in ``extra["occurrence_spans"]`` so
    persistence can attach one evidence reference per occurrence instead
    of silently dropping repeat mentions.
    """
    seen: dict[tuple[str, str], EntityCandidate] = {}
    for candidate in sorted(candidates, key=lambda c: -c.confidence):
        key = (candidate.entity_type, candidate.normalized_name)
        if key not in seen:
            seen[key] = candidate
            candidate.extra.setdefault("occurrence_spans", [])
            candidate.extra["occurrence_spans"].append(candidate.span)
            continue
        existing = seen[key]
        # Merge extra info (e.g. parent_location) from later occurrences.
        for k, v in (candidate.extra or {}).items():
            existing.extra.setdefault(k, v)
        for alias in candidate.aliases:
            if alias not in existing.aliases:
                existing.aliases.append(alias)
        # Preserve every occurrence as evidence.
        existing.extra.setdefault("occurrence_spans", [])
        if candidate.span not in existing.extra["occurrence_spans"]:
            existing.extra["occurrence_spans"].append(candidate.span)
        for span in (candidate.extra or {}).get("occurrence_spans", []):
            if span not in existing.extra["occurrence_spans"]:
                existing.extra["occurrence_spans"].append(span)
    return list(seen.values())
