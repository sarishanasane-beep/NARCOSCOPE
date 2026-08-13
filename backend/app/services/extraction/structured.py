"""Structured NARCOSCOPE TXT parser.

Structured documents use labelled blocks that tell the parser what each
fact means:

    PERSON:
    NAME: John Doe
    ROLE: ACCUSED
    STATUS: ARRESTED

The section header and the field labels are EXPLICIT semantic
instructions: ``DRUG:`` means the value is a drug, never a person; the
parser runs no generic name-detection heuristics on the values. The
parser is label-driven (section/field names), never value-driven — there
is no hard-coded document or name anywhere in it.

Everything produced is a CANDIDATE with the exact block text as
evidence. Nothing is auto-confirmed. Sections not yet supported are
ignored safely; malformed blocks are skipped without crashing.

The generic deterministic engine (``engine.run_extraction``) is
untouched: ``detect_structured`` decides which pipeline processes a
document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.extraction.dates import DateInfo, extract_dates
from app.services.extraction.engine import CaseCandidate, CaseMatcher, ExtractionResult
from app.services.extraction.entities import (
    ENTITY_TYPE_LOCATION,
    ENTITY_TYPE_ORGANIZATION,
    ENTITY_TYPE_OTHER,
    ENTITY_TYPE_PERSON,
    EntityCandidate,
)
from app.services.extraction.events import EventCandidate
from app.services.extraction.relationships import FactCandidate, RelationshipCandidate
from app.services.extraction.spans import TextSpan
from app.utils.text import normalize_name

ENTITY_TYPE_DRUG = "DRUG"
ENTITY_TYPE_VEHICLE = "VEHICLE"
ENTITY_TYPE_CASE = "CASE"

# Values that mean "the source did not provide a person's identity".
_MISSING_PERSON_MARKERS = {
    "unknown", "not provided", "not_provided", "unnamed", "unnamed accused",
    "n/a", "none", "unknown / not provided", "unknown/not provided",
}

# Supported sections. Adding a new section here (plus a handler in the
# table below) extends the parser without rewriting it.
SECTION_NAMES: set[str] = {
    "DOCUMENT",
    "CASE",
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "DRUG",
    "VEHICLE",
    "ARREST",
    "SEIZURE",
    "CONVICTION",
    "EVENT",
    "INVESTIGATION",
    "RELATIONSHIP",
    "NOTE",
}

# Entity type a declared section maps to (by explicit section label).
_ENTITY_TYPE_BY_SECTION: dict[str, str] = {
    "PERSON": ENTITY_TYPE_PERSON,
    "ORGANIZATION": ENTITY_TYPE_ORGANIZATION,
    "LOCATION": ENTITY_TYPE_LOCATION,
    "DRUG": ENTITY_TYPE_DRUG,
    "VEHICLE": ENTITY_TYPE_VEHICLE,
}

# Known field labels (for structured detection). A section is only
# treated as structured content when at least one of these appears.
KNOWN_FIELDS: set[str] = {
    "TITLE", "DATE", "SOURCE", "SOURCE_TYPE",
    "NAME", "TYPE", "NUMBER", "CASE_NUMBER", "JURISDICTION",
    "ROLE", "STATUS", "ALIASES",
    "QUANTITY", "REGISTRATION", "VALUE",
    "PERSON", "ARRESTED_BY_ORGANIZATION", "LOCATION",
    "DRUG", "VEHICLE", "DESCRIPTION", "RELATION", "RELATIONSHIP_TYPE",
    "TARGET", "TARGET_TYPE", "CLASSIFICATION", "EVIDENCE",
    "TIME", "DATE_PRECISION", "DURATION", "MENTION_CONTEXT",
    "SENTENCE", "COURT", "PRECISION", "TEXT",
}

_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_ ]{0,40}):\s*$")
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_ ]{0,60}):\s*(.*)$")


@dataclass
class Field:
    name: str
    value: str
    value_start: int  # offset of the value inside the cleaned text


@dataclass
class Block:
    section: str
    start: int  # offset of the header line
    end: int  # offset just past the last content line
    fields: list[Field] = field(default_factory=list)

    def get(self, name: str) -> str | None:
        for entry in self.fields:
            if entry.name == name and entry.value:
                return entry.value
        return None

    def text(self, text: str) -> str:
        return text[self.start : self.end]

    def span(self, text: str) -> TextSpan:
        return TextSpan(start=self.start, end=self.end, text=self.text(text))


@dataclass
class StructuredParseResult:
    metadata: dict
    result: ExtractionResult
    # Structured validation issues found while parsing (unknown IDs,
    # invalid types, conflicting duplicate declarations). Each entry is a
    # dict: {"block": ..., "id": ..., "message": ...}. Nothing is silently
    # repaired — the issue is surfaced for human review.
    validation: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _match_header(line: str) -> str | None:
    """Return the canonical section name when ``line`` is a section header.

    A header is a line whose entire content is exactly ``SECTION:``.
    Nothing may follow the colon, so ordinary prose containing the word
    "PERSON" (e.g. "PERSON: John was seen") is never mistaken for a
    structured document.
    """
    match = _HEADER_RE.match(line.strip())
    if not match:
        return None
    name = match.group(1).strip().upper()
    return name if name in SECTION_NAMES else None


def _match_field(line: str) -> tuple[str, str, int] | None:
    """Parse a ``FIELD: value`` line. Returns ``(name, value, value_start)``.

    ``value_start`` is computed on the ORIGINAL line (leading whitespace
    preserved) so document offsets stay exact.
    """
    match = _FIELD_RE.match(line.strip())
    if not match:
        return None
    name = match.group(1).strip().upper()
    value = match.group(2).strip()
    if not value:
        return None  # malformed "NAME:" — never create an empty fact
    colon = line.find(":")
    if colon < 0:
        return None
    cursor = colon + 1
    while cursor < len(line) and line[cursor] in " \t":
        cursor += 1
    return name, value, cursor


def _parse_blocks(text: str) -> list[Block]:
    """Split the cleaned text into labelled blocks with document offsets."""
    blocks: list[Block] = []
    current: Block | None = None
    offset = 0
    for raw in text.split("\n"):
        line = raw.rstrip()
        header = _match_header(line)
        if header is not None:
            current = Block(section=header, start=offset, end=offset + len(line))
            blocks.append(current)
        elif current is not None:
            parsed = _match_field(line)
            if parsed is not None:
                name, value, value_start = parsed
                current.fields.append(Field(name=name, value=value, value_start=offset + value_start))
                current.end = offset + len(line)
        offset += len(raw) + 1
    return blocks


def detect_structured(text: str) -> bool:
    """True when the text looks like a structured NARCOSCOPE document.

    Two formats are recognized:

    - v2: the canonical header line
      ``NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT`` (authoritative
      marker — never detected from case names or prose keywords);
    - v1: at least two whole-line ``SECTION:`` headers, or one header
      plus at least one known field line inside it.

    The check is structural, never a keyword-in-prose scan.
    """
    if not text or not text.strip():
        return False
    if _is_v2_document(text):
        return True
    headers = 0
    field_lines = 0
    for raw in text.split("\n"):
        line = raw.strip()
        if _match_header(line) is not None:
            headers += 1
            continue
        parsed = _match_field(line)
        if parsed is not None and parsed[0] in KNOWN_FIELDS:
            field_lines += 1
    if headers >= 2:
        return True
    return headers == 1 and field_lines >= 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _date_info(text: str, value: str, value_start: int) -> DateInfo | None:
    """Parse a DATE field value into a DateInfo with document offsets."""
    if not value:
        return None
    found = extract_dates(value)
    if not found:
        return None
    source = found[0]
    return DateInfo(
        normalized=source.normalized,
        original=source.original,
        precision=source.precision,
        span=TextSpan(start=value_start, end=value_start + len(value), text=value),
    )


def _truncate(text: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    return cut[:last_space] if last_space > 0 else cut


def _is_missing_person(value: str | None) -> bool:
    """True when a PERSON field means "identity not provided".

    Never creates a fake "Unknown" / "Unnamed Accused" person from these
    markers — the missing identity is preserved as missing.
    """
    if not value:
        return False
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return normalized in _MISSING_PERSON_MARKERS


# ---------------------------------------------------------------------------
# Entity declarations
# ---------------------------------------------------------------------------


def _entity_candidate(
    section: str,
    name: str,
    block: Block,
    text: str,
    extra: dict | None = None,
) -> EntityCandidate:
    return EntityCandidate(
        name=name,
        entity_type=_ENTITY_TYPE_BY_SECTION[section],
        span=block.span(text),
        confidence=0.9,
        reason=f"structured {section} section",
        extra={**(extra or {}), "occurrence_spans": [block.span(text)]},
    )


def _dedupe_entities(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    """One candidate per (entity_type, normalized name); keep all block spans."""
    seen: dict[tuple[str, str], EntityCandidate] = {}
    for candidate in candidates:
        key = (candidate.entity_type, candidate.normalized_name)
        existing = seen.get(key)
        if existing is None:
            seen[key] = candidate
            continue
        for key_name, value in (candidate.extra or {}).items():
            existing.extra.setdefault(key_name, value)
        for span in candidate.extra.get("occurrence_spans") or []:
            if span not in existing.extra["occurrence_spans"]:
                existing.extra["occurrence_spans"].append(span)
    return list(seen.values())


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _case_candidate(
    block: Block,
    text: str,
    matcher: CaseMatcher,
) -> CaseCandidate | None:
    number = block.get("NUMBER") or block.get("CASE_NUMBER")
    name = block.get("NAME")
    if not number and not name:
        return None  # malformed block — nothing to create
    category = block.get("TYPE")
    jurisdiction = block.get("JURISDICTION")
    status = block.get("STATUS")
    description = block.get("DESCRIPTION")
    span = block.span(text)
    existing_id, match_kind = matcher(number, name)
    if match_kind == "exact_number":
        return CaseCandidate(
            case_number=number, case_name=name, action="link", existing_case_id=existing_id,
            jurisdiction=jurisdiction, span=span, confidence=0.9,
            reason="structured CASE section — official case number matches an existing case",
            category=category, status=status, description=description,
        )
    if match_kind == "possible_name":
        return CaseCandidate(
            case_number=number, case_name=name, action="link", existing_case_id=existing_id,
            jurisdiction=jurisdiction, span=span, confidence=0.7,
            reason="structured CASE section — possible case name match, human confirmation required",
            category=category, status=status, description=description,
        )
    return CaseCandidate(
        case_number=number, case_name=name, action="create",
        jurisdiction=jurisdiction, span=span, confidence=0.9,
        reason="structured CASE section", category=category, status=status, description=description,
    )


def _dedupe_cases(candidates: list[CaseCandidate]) -> list[CaseCandidate]:
    """Merge repeated references to the same case by name/number.

    The first candidate wins; a later numbered reference is preferred over
    a name-only one and category information is preserved.
    """
    by_name: dict[str, CaseCandidate] = {}
    by_number: dict[str, CaseCandidate] = {}
    for candidate in candidates:
        if candidate.case_name:
            existing = by_name.get(candidate.case_name)
            if existing is None:
                by_name[candidate.case_name] = candidate
            elif existing.case_number is None and candidate.case_number:
                candidate.category = candidate.category or existing.category
                by_name[candidate.case_name] = candidate
            elif not existing.category and candidate.category:
                existing.category = candidate.category
        elif candidate.case_number:
            by_number.setdefault(candidate.case_number, candidate)
    return list(by_name.values()) + list(by_number.values())


# ---------------------------------------------------------------------------
# Relationship endpoint resolution
# ---------------------------------------------------------------------------


def _relationship_type(block: Block) -> str | None:
    """The relationship-type field of a RELATIONSHIP block.

    Documents in the wild use ``RELATIONSHIP_TYPE``, ``RELATION`` or
    ``TYPE`` for the same explicit field — all are accepted so no valid
    structured relationship is ever dropped.
    """
    for name in ("RELATIONSHIP_TYPE", "RELATION", "TYPE"):
        value = block.get(name)
        if value:
            return value
    return None


def _endpoint_type(
    name: str,
    entity_by_name: dict[str, EntityCandidate],
    default: str = ENTITY_TYPE_OTHER,
) -> str:
    entity = entity_by_name.get(normalize_name(name))
    if entity is not None:
        return entity.entity_type
    return default


def _entity_for_endpoint(
    name: str,
    entity_by_name: dict[str, EntityCandidate],
    case_names: set[str],
    text: str,
    block: Block,
    reason: str,
) -> EntityCandidate | None:
    """Entity candidate for a relationship endpoint not otherwise declared.

    A case name referenced by an explicit RELATIONSHIP block needs an
    entity endpoint for the graph edge (the existing graph only connects
    entity nodes). The entity is created ONLY then — a CASE block alone
    never produces a duplicate OTHER entity.
    """
    if normalize_name(name) in entity_by_name:
        return None
    if normalize_name(name) not in case_names:
        return None
    return EntityCandidate(
        name=name,
        entity_type=ENTITY_TYPE_CASE,
        span=block.span(text),
        confidence=0.85,
        reason=reason,
        extra={"structured_kind": "CASE", "occurrence_spans": [block.span(text)]},
    )


# ---------------------------------------------------------------------------
# v2 format — NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT
#
# The v2 contract is ID-centric and deterministic. Each block declares an
# authoritative ID (CASE_ID / ENTITY_ID / EVENT_ID / RELATIONSHIP_ID /
# FACT_ID) and the parser resolves everything by those IDs — never by
# guessing from prose:
#
#     NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT
#     FORMAT_VERSION: 2
#
#     CASE
#     CASE_ID: OPERATION-WHITE-STRIKE
#     CASE_NAME: Operation WHITE STRIKE
#
#     ENTITY
#     ENTITY_ID: ENT-LAXMAN
#     NAME: Laxman Compound
#     TYPE: LOCATION
#
# The declared TYPE is authoritative: an ENTITY block declaring
# ``TYPE: LOCATION`` is NEVER reclassified as a person by generic
# heuristics. Only explicit RELATIONSHIP blocks create relationships, and
# their SOURCE/TARGET must resolve to declared IDs/names — an unknown ID
# is a structured validation error, never a fabricated entity.
# ---------------------------------------------------------------------------

_V2_HEADER_RE = re.compile(
    r"^\s*NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT\s*$",
    re.IGNORECASE | re.MULTILINE,
)

V2_SECTION_NAMES: set[str] = {
    "DOCUMENT", "CASE", "ENTITY", "EVENT", "RELATIONSHIP", "FACT", "NOTE",
}

# Bare v2 section-header line: the entire line is exactly a section name.
_V2_HEADER_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]{0,40})$")
# v2 field line: ``FIELD: value``.
_V2_FIELD_RE = re.compile(r"^([A-Z][A-Z0-9_ ]{0,60}):\s*(.*)$")

# Document-metadata fields accepted in the v2 preamble (before the first
# section header) — collected into a synthetic DOCUMENT block so
# publication-date metadata is never lost.
_V2_DOCUMENT_FIELDS: set[str] = {
    "TITLE", "DATE", "PUBLICATION_DATE", "SOURCE", "SOURCE_TYPE", "DOCUMENT_ID",
}

# Entity types accepted by the v2 contract. An ENTITY block declaring any
# other TYPE is a structured validation error — never silently coerced.
_V2_ENTITY_TYPES: set[str] = {
    "PERSON", "ORGANIZATION", "LOCATION", "DRUG", "VEHICLE", "CASE",
    "OTHER", "AGENCY", "PROPERTY",
}


# v2 aliases for the entity type field: ``TYPE`` (canonical) and
# ``ENTITY_TYPE`` are both accepted.
def _v2_entity_type(block: Block) -> str | None:
    for name in ("TYPE", "ENTITY_TYPE"):
        value = block.get(name)
        if value:
            return value.strip().upper()
    return None


def _is_v2_document(text: str) -> bool:
    return bool(text) and _V2_HEADER_RE.search(text) is not None


def _parse_v2_blocks(text: str) -> list[Block]:
    """Split a v2 document into labelled blocks with document offsets.

    v2 headers are BARE section names (``CASE`` on its own line). Field
    lines are ``FIELD: value``. A line that is neither a header nor a
    field continues the previous field's value (wrapped descriptions stay
    one value). The canonical header line and FORMAT_VERSION are preamble
    and are ignored; document-metadata fields before the first section
    header are collected into a synthetic DOCUMENT block.
    """
    blocks: list[Block] = []
    current: Block | None = None
    pending_document: Block | None = None
    offset = 0
    for raw in text.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        header = _V2_HEADER_LINE_RE.match(stripped) if stripped else None
        if header is not None and header.group(1) in V2_SECTION_NAMES:
            current = Block(section=header.group(1), start=offset, end=offset + len(line))
            blocks.append(current)
            offset += len(raw) + 1
            continue
        if current is not None:
            field = _V2_FIELD_RE.match(stripped)
            if field is not None:
                name = field.group(1)
                value = field.group(2).strip()
                colon = line.find(":")
                cursor = colon + 1
                while cursor < len(line) and line[cursor] in " \t":
                    cursor += 1
                # Empty values are kept so a wrapped value on the next
                # line can fill the field.
                current.fields.append(
                    Field(name=name, value=value, value_start=offset + cursor)
                )
                current.end = offset + len(line)
            elif stripped and not _V2_HEADER_RE.match(stripped):
                # Continuation of the previous field's value.
                if current.fields:
                    last = current.fields[-1]
                    last.value = (
                        (last.value + " " + stripped).strip() if last.value else stripped
                    )
                    current.end = offset + len(line)
        else:
            # Preamble before the first section header.
            field = _V2_FIELD_RE.match(stripped) if stripped else None
            if field is not None and field.group(1) in _V2_DOCUMENT_FIELDS:
                if pending_document is None:
                    pending_document = Block(section="DOCUMENT", start=0, end=0)
                    blocks.append(pending_document)
                value = field.group(2).strip()
                colon = line.find(":")
                cursor = colon + 1
                while cursor < len(line) and line[cursor] in " \t":
                    cursor += 1
                pending_document.fields.append(
                    Field(name=field.group(1), value=value, value_start=offset + cursor)
                )
                pending_document.end = offset + len(line)
        offset += len(raw) + 1
    return blocks


def _v2_metadata(block: Block, text: str, metadata: dict, dates: list) -> None:
    metadata["title"] = block.get("TITLE")
    metadata["source"] = block.get("SOURCE")
    metadata["source_type"] = block.get("SOURCE_TYPE")
    # The publication date is DOCUMENT metadata — it is never copied onto
    # events; only an explicit EVENT DATE establishes an event date.
    raw_date = block.get("PUBLICATION_DATE") or block.get("DATE")
    if raw_date:
        field_name = "PUBLICATION_DATE" if block.get("PUBLICATION_DATE") else "DATE"
        info = _date_info(text, raw_date, _value_start(block, field_name))
        if info is not None:
            metadata["date"] = info
            dates.append(info)


def _v2_case(
    block: Block,
    text: str,
    matcher: CaseMatcher,
    validation: list[dict],
) -> CaseCandidate | None:
    case_id = block.get("CASE_ID")
    name = block.get("CASE_NAME") or block.get("NAME")
    if not name:
        validation.append({
            "block": "CASE",
            "id": case_id or "?",
            "message": "CASE block is missing CASE_NAME. No case was created.",
        })
        return None
    category = block.get("CASE_TYPE") or block.get("TYPE")
    status = block.get("STATUS")
    description = block.get("DESCRIPTION")
    jurisdiction = block.get("JURISDICTION")
    existing_id, match_kind = matcher(None, name)
    span = block.span(text)
    if match_kind == "exact_number":
        return CaseCandidate(
            case_number=None, case_name=name, action="link", existing_case_id=existing_id,
            jurisdiction=jurisdiction, span=span, confidence=0.9,
            reason="structured CASE section (v2) — official case matches an existing case",
            category=category, status=status, description=description, structured_id=case_id,
        )
    if match_kind == "possible_name":
        return CaseCandidate(
            case_number=None, case_name=name, action="link", existing_case_id=existing_id,
            jurisdiction=jurisdiction, span=span, confidence=0.7,
            reason="structured CASE section (v2) — possible case name match, human confirmation required",
            category=category, status=status, description=description, structured_id=case_id,
        )
    return CaseCandidate(
        case_number=None, case_name=name, action="create",
        jurisdiction=jurisdiction, span=span, confidence=0.9,
        reason="structured CASE section (v2)",
        category=category, status=status, description=description, structured_id=case_id,
    )


def _v2_entity(
    block: Block,
    text: str,
    validation: list[dict],
) -> EntityCandidate | None:
    entity_id = block.get("ENTITY_ID")
    name = block.get("NAME")
    if not name:
        validation.append({
            "block": "ENTITY",
            "id": entity_id or "?",
            "message": "ENTITY block is missing NAME. No entity was created.",
        })
        return None
    entity_type = _v2_entity_type(block)
    if entity_type not in _V2_ENTITY_TYPES:
        validation.append({
            "block": "ENTITY",
            "id": entity_id or name,
            "message": (
                f"ENTITY '{name}' declares invalid TYPE "
                f"'{entity_type or '(missing)'}'. No entity was created."
            ),
        })
        return None
    extra: dict = {"structured_kind": entity_type}
    if entity_id:
        extra["entity_id"] = entity_id
    for key in ("ROLE", "STATUS", "MENTION_CONTEXT", "INVESTIGATIVE_STATUS", "DESCRIPTION"):
        value = block.get(key)
        if value:
            extra[key.lower()] = value
    if entity_type == "LOCATION":
        location_type = block.get("LOCATION_TYPE")
        if location_type:
            extra["location_type"] = location_type
    elif entity_type == "DRUG":
        for key in ("QUANTITY", "VALUE", "STATUS"):
            value = block.get(key)
            if value:
                extra[key.lower()] = value
    elif entity_type == "VEHICLE":
        for key in ("REGISTRATION", "STATUS"):
            value = block.get(key)
            if value:
                extra[key.lower()] = value
    if block.get("EVIDENCE"):
        extra["evidence_snippet"] = block.get("EVIDENCE")
    return EntityCandidate(
        name=name,
        entity_type=entity_type,
        span=block.span(text),
        confidence=0.9,
        reason="structured ENTITY section (v2)",
        extra=extra,
    )


def _v2_event(
    block: Block,
    text: str,
    dates: list,
    validation: list[dict],
) -> EventCandidate | None:
    event_id = block.get("EVENT_ID")
    name = block.get("NAME")
    event_type = block.get("TYPE") or "OTHER"
    description = block.get("DESCRIPTION")
    if not name and not description:
        validation.append({
            "block": "EVENT",
            "id": event_id or "?",
            "message": "EVENT block is missing NAME and DESCRIPTION. No event was created.",
        })
        return None
    title = name or (_truncate(description, 120) if description else event_type)
    location = block.get("LOCATION")
    raw_date = block.get("DATE")
    date = _date_info(text, raw_date, _value_start(block, "DATE")) if raw_date else None
    if date is not None:
        dates.append(date)
    extra: dict = {
        "event_id": event_id,
        "description": description,
        "structured_kind": "EVENT",
        "status": block.get("STATUS"),
        "duration": block.get("DURATION"),
        "organization": block.get("ORGANIZATION"),
        "drug": block.get("DRUG"),
        "vehicle": block.get("VEHICLE"),
        "person": block.get("PERSON"),
    }
    raw_time = block.get("TIME")
    if raw_time:
        extra["time"] = raw_time
    raw_precision = block.get("DATE_PRECISION") or block.get("PRECISION")
    if raw_precision:
        extra["date_precision"] = raw_precision
    if block.get("EVIDENCE"):
        extra["evidence_snippet"] = block.get("EVIDENCE")
    person_field = block.get("PERSON")
    if _is_missing_person(person_field) or (event_type == "ARREST" and not person_field):
        extra["accused_identity"] = "NOT_PROVIDED"
    return EventCandidate(
        event_type=event_type,
        title=title,
        span=block.span(text),
        confidence=0.9,
        reason="structured EVENT section (v2)",
        date=date,
        location_name=location,
        extra=extra,
    )


def _v2_resolve_endpoint(
    ref: str | None,
    entity_by_id: dict[str, EntityCandidate],
    entity_by_name: dict[str, EntityCandidate],
    case_by_id: dict[str, str],
    case_by_name: dict[str, str],
) -> tuple[str, str] | None:
    """Resolve a RELATIONSHIP/FACT endpoint to ``(name, type)``.

    Order: declared ENTITY_ID, declared entity name, declared CASE_ID,
    declared case name. Unknown references return None — the caller
    records a validation error; no fake entity is ever created and no
    fuzzy matching is attempted.
    """
    if not ref:
        return None
    trimmed = ref.strip()
    upper = trimmed.upper()
    entity = entity_by_id.get(upper)
    if entity is not None:
        return entity.name, entity.entity_type
    entity = entity_by_name.get(normalize_name(trimmed))
    if entity is not None:
        return entity.name, entity.entity_type
    case_name = case_by_id.get(upper) or case_by_name.get(normalize_name(trimmed))
    if case_name:
        return case_name, ENTITY_TYPE_CASE
    return None


def _v2_relationship(
    block: Block,
    text: str,
    entity_by_id: dict[str, EntityCandidate],
    entity_by_name: dict[str, EntityCandidate],
    case_by_id: dict[str, str],
    case_by_name: dict[str, str],
    validation: list[dict],
    seen: set[tuple[str, str, str]],
) -> RelationshipCandidate | None:
    rel_id = block.get("RELATIONSHIP_ID")
    source_ref = block.get("SOURCE")
    target_ref = block.get("TARGET")
    rel_type = block.get("TYPE") or block.get("RELATIONSHIP_TYPE") or block.get("RELATION")
    if not source_ref or not target_ref or not rel_type:
        validation.append({
            "block": "RELATIONSHIP",
            "id": rel_id or "?",
            "message": "RELATIONSHIP block is missing SOURCE, TARGET or TYPE. No relationship was created.",
        })
        return None
    source = _v2_resolve_endpoint(
        source_ref, entity_by_id, entity_by_name, case_by_id, case_by_name
    )
    target = _v2_resolve_endpoint(
        target_ref, entity_by_id, entity_by_name, case_by_id, case_by_name
    )
    missing = []
    if source is None:
        missing.append(f"Source '{source_ref}' does not exist")
    if target is None:
        missing.append(f"Target '{target_ref}' does not exist")
    if missing:
        validation.append({
            "block": "RELATIONSHIP",
            "id": rel_id or "?",
            "message": "; ".join(missing) + ". No relationship was created.",
        })
        return None
    # Triple-level dedup as a safety net beyond RELATIONSHIP_ID.
    dup_key = (normalize_name(source[0]), rel_type, normalize_name(target[0]))
    if dup_key in seen:
        return None
    seen.add(dup_key)
    conflicts: list[str] = []
    source_type = _resolve_endpoint_type(block.get("SOURCE_TYPE"), source[1], source[0], conflicts)
    target_type = _resolve_endpoint_type(block.get("TARGET_TYPE"), target[1], target[0], conflicts)
    classification = (block.get("CLASSIFICATION") or "DIRECT").strip().upper()
    extra: dict = {}
    if rel_id:
        extra["relationship_id"] = rel_id
    if block.get("EVIDENCE"):
        extra["evidence_snippet"] = block.get("EVIDENCE")
    if conflicts:
        extra["type_conflicts"] = conflicts
    return RelationshipCandidate(
        source_name=source[0],
        source_type=source_type,
        relationship_type=rel_type,
        target_name=target[0],
        target_type=target_type,
        span=block.span(text),
        confidence=0.9,
        reason=f"structured RELATIONSHIP section (v2) ({rel_type})",
        classification=classification,
        extra=extra,
    )


def _v2_fact(
    block: Block,
    text: str,
    case_name: str | None,
    entity_by_id: dict[str, EntityCandidate],
    entity_by_name: dict[str, EntityCandidate],
    validation: list[dict],
) -> FactCandidate | None:
    fact_id = block.get("FACT_ID")
    subject_ref = block.get("SUBJECT") or block.get("SUBJECT_ID") or block.get("SUBJECT_NAME")
    predicate = block.get("PREDICATE") or block.get("PREDICATE_TYPE") or "FACT"
    object_ref = block.get("OBJECT") or block.get("OBJECT_ID") or block.get("OBJECT_NAME")
    subject = (
        _v2_resolve_endpoint(subject_ref, entity_by_id, entity_by_name, {}, {})
        if subject_ref
        else None
    )
    case_ref = None
    if subject is None:
        if case_name:
            # Facts in a case document are attributed to the declared case
            # when no explicit subject is given — never to an invented person.
            subject = (case_name, ENTITY_TYPE_CASE)
            case_ref = case_name
        else:
            validation.append({
                "block": "FACT",
                "id": fact_id or "?",
                "message": "FACT block has no subject and the document declares no case. The fact was preserved in the document but no candidate was created.",
            })
            return None
    object_info = (
        _v2_resolve_endpoint(object_ref, entity_by_id, entity_by_name, {}, {})
        if object_ref
        else None
    )
    extra: dict = {}
    if fact_id:
        extra["fact_id"] = fact_id
    if block.get("DESCRIPTION"):
        extra["description"] = block.get("DESCRIPTION")
    if block.get("STATUS"):
        extra["status"] = block.get("STATUS")
    if block.get("EVIDENCE"):
        extra["evidence_snippet"] = block.get("EVIDENCE")
    return FactCandidate(
        subject_name=subject[0],
        subject_type=subject[1],
        predicate=predicate,
        object_name=object_info[0] if object_info else None,
        object_type=object_info[1] if object_info else None,
        span=block.span(text),
        confidence=0.9,
        reason="structured FACT section (v2)",
        case_ref=case_ref,
        extra=extra,
    )


def _parse_v2(
    text: str,
    *,
    matcher: CaseMatcher,
) -> StructuredParseResult:
    """Parse a v2 NARCOSCOPE structured document into candidates.

    Everything produced is a PENDING candidate with the exact block text
    as evidence. Validation issues (unknown IDs, invalid types, conflicts)
    are collected in ``StructuredParseResult.validation`` and surfaced for
    human review — never silently repaired.
    """
    blocks = _parse_v2_blocks(text)
    metadata: dict = {}
    validation: list[dict] = []
    entities: list[EntityCandidate] = []
    cases: list[CaseCandidate] = []
    events: list[EventCandidate] = []
    relationships: list[RelationshipCandidate] = []
    facts: list[FactCandidate] = []
    dates: list[DateInfo] = []

    entity_by_id: dict[str, EntityCandidate] = {}
    case_by_id: dict[str, str] = {}
    case_by_name: dict[str, str] = {}
    case_name: str | None = None
    seen_relationships: set[tuple[str, str, str]] = set()

    # Pass A — declarations: DOCUMENT metadata, CASE, ENTITY blocks.
    for block in blocks:
        if block.section == "DOCUMENT":
            _v2_metadata(block, text, metadata, dates)
            continue
        if block.section == "CASE":
            candidate = _v2_case(block, text, matcher, validation)
            if candidate is None:
                continue
            cid = (candidate.structured_id or "").strip().upper()
            if cid:
                existing = next(
                    (c for c in cases if (c.structured_id or "").strip().upper() == cid),
                    None,
                )
                if existing is not None:
                    if (existing.case_name or "").lower() != (candidate.case_name or "").lower():
                        validation.append({
                            "block": "CASE",
                            "id": cid,
                            "message": (
                                f"CASE_ID {cid} is declared with conflicting names "
                                f"('{existing.case_name}' vs '{candidate.case_name}'). "
                                "The first declaration was kept."
                            ),
                        })
                    else:
                        # Merge non-conflicting metadata from later
                        # declarations of the same CASE_ID.
                        if existing.category is None and candidate.category:
                            existing.category = candidate.category
                        if existing.status is None and candidate.status:
                            existing.status = candidate.status
                        if existing.description is None and candidate.description:
                            existing.description = candidate.description
                        if existing.jurisdiction is None and candidate.jurisdiction:
                            existing.jurisdiction = candidate.jurisdiction
                    continue
            cases.append(candidate)
            if candidate.case_name:
                case_by_name[normalize_name(candidate.case_name)] = candidate.case_name
                case_name = case_name or candidate.case_name
            if cid and candidate.case_name:
                case_by_id[cid] = candidate.case_name
            continue
        if block.section == "ENTITY":
            candidate = _v2_entity(block, text, validation)
            if candidate is None:
                continue
            eid = (candidate.extra.get("entity_id") or "").strip().upper()
            if eid:
                existing = entity_by_id.get(eid)
                if existing is not None:
                    if existing.name != candidate.name or existing.entity_type != candidate.entity_type:
                        validation.append({
                            "block": "ENTITY",
                            "id": eid,
                            "message": (
                                f"ENTITY_ID {eid} is declared with conflicting values "
                                f"(first: {existing.name}/{existing.entity_type}; "
                                f"second: {candidate.name}/{candidate.entity_type}). "
                                "The first declaration was kept."
                            ),
                        })
                    else:
                        for key, value in candidate.extra.items():
                            existing.extra.setdefault(key, value)
                    continue
                entity_by_id[eid] = candidate
            entities.append(candidate)
            continue

    entities = _dedupe_entities(entities)
    entity_by_name = {entity.normalized_name: entity for entity in entities}

    # Pass B — EVENT, RELATIONSHIP, FACT blocks (depend on declarations).
    for block in blocks:
        if block.section == "EVENT":
            candidate = _v2_event(block, text, dates, validation)
            if candidate is None:
                continue
            eid = (candidate.extra.get("event_id") or "").strip().upper()
            if eid and any(
                (e.extra.get("event_id") or "").strip().upper() == eid for e in events
            ):
                continue
            events.append(candidate)
            continue
        if block.section == "RELATIONSHIP":
            candidate = _v2_relationship(
                block, text, entity_by_id, entity_by_name,
                case_by_id, case_by_name, validation, seen_relationships,
            )
            if candidate is None:
                continue
            rid = (candidate.extra.get("relationship_id") or "").strip().upper()
            if rid and any(
                (r.extra.get("relationship_id") or "").strip().upper() == rid
                for r in relationships
            ):
                continue
            relationships.append(candidate)
            continue
        if block.section == "FACT":
            candidate = _v2_fact(
                block, text, case_name, entity_by_id, entity_by_name, validation
            )
            if candidate is not None:
                facts.append(candidate)
            continue
        # NOTE (and any future sections without a handler) produce no
        # candidates — notes are annotations, not facts.

    result = ExtractionResult(
        entities=entities,
        events=events,
        relationships=relationships,
        facts=facts,
        cases=cases,
        claims=[],
        dates=dates,
        sentences=[],
    )
    return StructuredParseResult(metadata=metadata, result=result, validation=validation)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_structured(
    text: str,
    *,
    case_matcher: CaseMatcher | None = None,
) -> StructuredParseResult:
    """Parse a structured NARCOSCOPE TXT into candidates + document metadata.

    Dispatches on the format: the v2 contract (canonical
    ``NARCOSCOPE_STRUCTURED_INVESTIGATION_DOCUMENT`` header) is parsed by
    ``_parse_v2``; the labelled ``SECTION:`` format keeps the original
    parser. Both produce the same candidate types and never run generic
    NLP over declared fields.
    """
    matcher = case_matcher or (lambda _n, _m: (None, "none"))

    if _is_v2_document(text):
        return _parse_v2(text, matcher=matcher)

    blocks = _parse_blocks(text)

    entities: list[EntityCandidate] = []
    cases: list[CaseCandidate] = []
    events: list[EventCandidate] = []
    relationships: list[RelationshipCandidate] = []
    facts: list[FactCandidate] = []
    dates: list[DateInfo] = []
    metadata: dict = {}

    # Pass A — declarations: DOCUMENT metadata, CASE/INVESTIGATION cases,
    # PERSON/ORGANIZATION/LOCATION/DRUG/VEHICLE entities.
    for block in blocks:
        if block.section == "DOCUMENT":
            metadata = {
                "title": block.get("TITLE"),
                "source": block.get("SOURCE"),
                "source_type": block.get("SOURCE_TYPE"),
            }
            raw_date = block.get("DATE")
            if raw_date:
                info = _date_info(text, raw_date, _value_start(block, "DATE"))
                if info is not None:
                    metadata["date"] = info
                    dates.append(info)
            continue
        if block.section in ("CASE", "INVESTIGATION"):
            candidate = _case_candidate(block, text, matcher)
            if candidate is not None:
                cases.append(candidate)
            continue
        if block.section in _ENTITY_TYPE_BY_SECTION:
            name = block.get("NAME")
            if not name:
                continue  # malformed block — skip safely
            extra: dict = {"structured_kind": block.section}
            description = block.get("DESCRIPTION")
            if description:
                extra["description"] = description
            if block.section == "PERSON":
                role = block.get("ROLE")
                status = block.get("STATUS")
                mention_context = block.get("MENTION_CONTEXT")
                if role:
                    extra["role"] = role
                if status:
                    extra["status"] = status
                # A MENTIONED person (government official, quotee, author) is
                # NOT an investigative subject. The explicit field preserves
                # that distinction — no inference is performed here.
                if mention_context:
                    extra["mention_context"] = mention_context
            elif block.section == "ORGANIZATION":
                role = block.get("ROLE")
                status = block.get("STATUS")
                if role:
                    extra["role"] = role
                if status:
                    extra["status"] = status
            elif block.section == "LOCATION":
                location_type = block.get("TYPE")
                if location_type:
                    extra["location_type"] = location_type
            elif block.section == "DRUG":
                for key in ("TYPE", "QUANTITY", "VALUE", "STATUS"):
                    value = block.get(key)
                    if value:
                        extra[key.lower()] = value
            elif block.section == "VEHICLE":
                for key in ("TYPE", "REGISTRATION", "STATUS"):
                    value = block.get(key)
                    if value:
                        extra[key.lower()] = value
            # An explicit EVIDENCE: field (when present) becomes the
            # reviewer-visible evidence snippet; the block span itself is
            # always kept as the exact evidence reference.
            if block.get("EVIDENCE"):
                extra["evidence_snippet"] = block.get("EVIDENCE")
            entities.append(_entity_candidate(block.section, name, block, text, extra))
            continue

    entities = _dedupe_entities(entities)
    cases = _dedupe_cases(cases)
    entity_by_name = {entity.normalized_name: entity for entity in entities}
    case_names = {
        normalize_name(case.case_name)
        for case in cases
        if case.case_name
    }
    seen_relationships: set[tuple[str, str, str]] = set()

    # Pass B — facts derived from explicit event/fact blocks and the
    # explicit RELATIONSHIP section.
    for block in blocks:
        if block.section == "ARREST":
            person = block.get("PERSON")
            if not person:
                continue
            location = block.get("LOCATION")
            raw_date = block.get("DATE")
            date = _date_info(text, raw_date, _value_start(block, "DATE")) if raw_date else None
            if date is not None:
                dates.append(date)
            if _is_missing_person(person):
                # The source reports an arrest without naming the accused:
                # no person entity, no relationship — the identity stays
                # explicitly NOT_PROVIDED.
                events.append(
                    EventCandidate(
                        event_type="ARREST",
                        title="Arrest (accused identity not provided)",
                        span=block.span(text),
                        confidence=0.9,
                        reason="structured ARREST section — accused not named in source",
                        date=date,
                        location_name=location,
                        extra={"structured_kind": "ARREST", "accused_identity": "NOT_PROVIDED"},
                    )
                )
                continue
            events.append(
                EventCandidate(
                    event_type="ARREST",
                    title=f"Arrest of {person}",
                    span=block.span(text),
                    confidence=0.9,
                    reason="structured ARREST section",
                    date=date,
                    location_name=location,
                    extra={"structured_kind": "ARREST"},
                )
            )
            # Adjustment: the ARRESTED_BY relationship exists ONLY when an
            # explicit arresting organization is present in the block. The
            # arresting party is never inferred from document context.
            arresting_org = block.get("ARRESTED_BY_ORGANIZATION")
            if arresting_org:
                relationships.append(
                    RelationshipCandidate(
                        source_name=person,
                        source_type=_endpoint_type(person, entity_by_name, ENTITY_TYPE_PERSON),
                        relationship_type="ARRESTED_BY",
                        target_name=arresting_org,
                        target_type=_endpoint_type(arresting_org, entity_by_name, ENTITY_TYPE_ORGANIZATION),
                        span=block.span(text),
                        confidence=0.9,
                        reason="structured ARREST section — explicit arresting organization",
                    )
                )
            continue

        if block.section == "SEIZURE":
            drug = block.get("DRUG")
            if not drug:
                continue
            location = block.get("LOCATION")
            raw_date = block.get("DATE")
            date = _date_info(text, raw_date, _value_start(block, "DATE")) if raw_date else None
            if date is not None:
                dates.append(date)
            events.append(
                EventCandidate(
                    event_type="SEIZURE",
                    title=f"Seizure of {drug}",
                    span=block.span(text),
                    confidence=0.9,
                    reason="structured SEIZURE section",
                    date=date,
                    location_name=location,
                    extra={
                        "structured_kind": "SEIZURE",
                        "quantity": block.get("QUANTITY"),
                        "value": block.get("VALUE"),
                    },
                )
            )
            continue

        if block.section == "CONVICTION":
            person = block.get("PERSON")
            if not person:
                continue
            status = block.get("STATUS") or "CONVICTED"
            facts.append(
                FactCandidate(
                    subject_name=person,
                    subject_type=_endpoint_type(person, entity_by_name, ENTITY_TYPE_PERSON),
                    predicate=status,
                    object_name=None,
                    object_type=None,
                    span=block.span(text),
                    confidence=0.9,
                    reason="structured CONVICTION section — explicit conviction record",
                    extra={
                        "sentence": block.get("SENTENCE"),
                        "court": block.get("COURT"),
                        "status": status,
                    },
                )
            )
            continue

        if block.section == "EVENT":
            event_type = block.get("TYPE") or "OTHER"
            description = block.get("DESCRIPTION")
            if not description and not event_type:
                continue
            title = _truncate(description) if description else event_type
            location = block.get("LOCATION")
            raw_date = block.get("DATE")
            date = _date_info(text, raw_date, _value_start(block, "DATE")) if raw_date else None
            if date is not None:
                dates.append(date)
            extra: dict = {
                "description": description,
                "structured_kind": "EVENT",
                "status": block.get("STATUS"),
                "duration": block.get("DURATION"),
                "organization": block.get("ORGANIZATION"),
                "drug": block.get("DRUG"),
                "vehicle": block.get("VEHICLE"),
                "person": block.get("PERSON"),
            }
            raw_time = block.get("TIME")
            if raw_time:
                extra["time"] = raw_time
            raw_precision = block.get("DATE_PRECISION") or block.get("PRECISION")
            if raw_precision:
                extra["date_precision"] = raw_precision
            if block.get("EVIDENCE"):
                extra["evidence_snippet"] = block.get("EVIDENCE")
            person_field = block.get("PERSON")
            if _is_missing_person(person_field) or (event_type == "ARREST" and not person_field):
                # An arrest is reported but the accused is not named:
                # the identity is preserved as NOT_PROVIDED, never invented.
                extra["accused_identity"] = "NOT_PROVIDED"
            events.append(
                EventCandidate(
                    event_type=event_type,
                    title=title,
                    span=block.span(text),
                    confidence=0.9,
                    reason="structured EVENT section",
                    date=date,
                    location_name=location,
                    extra=extra,
                )
            )
            continue

        if block.section == "RELATIONSHIP":
            source_name = block.get("SOURCE")
            relationship_type = _relationship_type(block)
            target_name = block.get("TARGET")
            if not source_name or not relationship_type or not target_name:
                continue  # malformed relationship — skip safely
            # Duplicate declarations of the same relationship in one
            # document are merged — one candidate, one trusted edge.
            dup_key = (
                normalize_name(source_name),
                relationship_type,
                normalize_name(target_name),
            )
            if dup_key in seen_relationships:
                continue
            seen_relationships.add(dup_key)
            # A declared case referenced as an endpoint gets an entity
            # representation ONLY because the graph edge requires it.
            for name in (source_name, target_name):
                endpoint_entity = _entity_for_endpoint(
                    name, entity_by_name, case_names, text, block,
                    reason="structured RELATIONSHIP section — endpoint is a declared case",
                )
                if endpoint_entity is not None:
                    entities.append(endpoint_entity)
                    entity_by_name[endpoint_entity.normalized_name] = endpoint_entity
            # Explicit SOURCE_TYPE / TARGET_TYPE take priority. When the
            # explicit type contradicts the type of a declared entity with
            # the same name, the conflict is surfaced for review instead of
            # being silently resolved (REQ 24).
            conflicts: list[str] = []
            source_type = _resolve_endpoint_type(
                block.get("SOURCE_TYPE"),
                _endpoint_type(source_name, entity_by_name),
                source_name,
                conflicts,
            )
            target_type = _resolve_endpoint_type(
                block.get("TARGET_TYPE"),
                _endpoint_type(target_name, entity_by_name),
                target_name,
                conflicts,
            )
            classification = (block.get("CLASSIFICATION") or "DIRECT").strip().upper()
            extra: dict = {}
            if block.get("EVIDENCE"):
                extra["evidence_snippet"] = block.get("EVIDENCE")
            if conflicts:
                extra["type_conflicts"] = conflicts
            relationships.append(
                RelationshipCandidate(
                    source_name=source_name,
                    source_type=source_type,
                    relationship_type=relationship_type,
                    target_name=target_name,
                    target_type=target_type,
                    span=block.span(text),
                    confidence=0.9,
                    reason=f"structured RELATIONSHIP section ({relationship_type})",
                    classification=classification,
                    extra=extra,
                )
            )
            continue

        # NOTE (and any future sections without a handler) produce no
        # candidates. Notes are annotations, not facts.

    result = ExtractionResult(
        entities=entities,
        events=events,
        relationships=relationships,
        facts=facts,
        cases=cases,
        claims=[],
        dates=dates,
        sentences=[],
    )
    return StructuredParseResult(metadata=metadata, result=result)


def _resolve_endpoint_type(
    explicit: str | None,
    declared: str,
    name: str,
    conflicts: list[str],
) -> str:
    """Explicit SOURCE_TYPE/TARGET_TYPE wins; conflicts are surfaced.

    When an explicit type contradicts the type of a declared entity with
    the same name, the explicit structured declaration is preserved and
    the conflict is recorded for human review — never silently resolved.
    """
    if not explicit:
        return declared
    explicit = explicit.strip().upper()
    if declared != ENTITY_TYPE_OTHER and declared != explicit:
        conflicts.append(f"{name}: declared {declared}, explicit {explicit}")
    return explicit


def _value_start(block: Block, name: str) -> int:
    for entry in block.fields:
        if entry.name == name:
            return entry.value_start
    return block.end
