"""Deterministic event extraction.

Detects event keywords and contextual patterns (arrested, seized, raid,
operation, searched, intercepted, investigation, court proceeding).
Dates, locations, case references and evidence are attached only when
supported by the source text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.extraction.case_numbers import CaseNumberCandidate
from app.services.extraction.dates import DateInfo
from app.services.extraction.dictionaries import EVENT_KEYWORDS
from app.services.extraction.entities import EntityCandidate, ENTITY_TYPE_LOCATION
from app.services.extraction.spans import TextSpan

_OPERATION_RE = re.compile(r"\bOperation\s+([A-Z][A-Za-z0-9]+)\b")
_ARREST_RE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?:was|were)\s+(?:also\s+)?arrested\s+(?:during|in)\s+"
    r"(?:the\s+)?(Operation\s+[A-Z][A-Za-z0-9]+)"
)


@dataclass
class EventCandidate:
    event_type: str
    title: str
    span: TextSpan
    confidence: float
    reason: str
    date: DateInfo | None = None
    location_name: str | None = None
    case_ref: str | None = None
    extra: dict = field(default_factory=dict)


def _inside(sentence: TextSpan, span: TextSpan) -> bool:
    return sentence.start <= span.start and span.end <= sentence.end


def _truncate(text: str, limit: int = 100) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    return cut[:last_space] if last_space > 0 else cut


def extract_events(
    text: str,
    sentences: list[TextSpan],
    entities: list[EntityCandidate],
    dates: list[DateInfo],
    case_numbers: list[CaseNumberCandidate],
) -> list[EventCandidate]:
    events: list[EventCandidate] = []

    for sentence in sentences:
        lower = sentence.text.lower()
        op_match = _OPERATION_RE.search(sentence.text)
        operation_name = op_match.group(0) if op_match else None
        date_in = next((d for d in dates if _inside(sentence, d.span)), None)
        location_in = next(
            (e for e in entities if e.entity_type == ENTITY_TYPE_LOCATION and _inside(sentence, e.span)),
            None,
        )
        case_in = next((c for c in case_numbers if _inside(sentence, c.span)), None)

        keyword_hits = {
            keyword: event_type
            for keyword, event_type in EVENT_KEYWORDS.items()
            if re.search(rf"\b{keyword}\b", lower)
        }
        for keyword, event_type in keyword_hits.items():
            if event_type == "OPERATION" and operation_name is None:
                continue
            arrest_match = _ARREST_RE.search(sentence.text) if event_type == "ARREST" else None
            if arrest_match:
                title = f"Arrest of {arrest_match.group(1)} during {arrest_match.group(2)}"
                confidence = 0.85
                reason = "arrest pattern during operation"
            elif event_type == "OPERATION" and operation_name:
                title = operation_name
                confidence = 0.85
                reason = "operation keyword"
            elif operation_name:
                title = f"{event_type.title()} during {operation_name}"
                confidence = 0.7
                reason = f"event keyword: {keyword} (during {operation_name})"
            else:
                title = _truncate(sentence.text)
                confidence = 0.6
                reason = f"event keyword: {keyword}"

            events.append(
                EventCandidate(
                    event_type=event_type,
                    title=title,
                    span=sentence,
                    confidence=confidence,
                    reason=reason,
                    date=date_in,
                    location_name=location_in.name if location_in else None,
                    case_ref=case_in.normalized if case_in else None,
                    extra={"keyword": keyword, "operation_name": operation_name},
                )
            )

    return _dedupe(events)


def _dedupe(events: list[EventCandidate]) -> list[EventCandidate]:
    seen: dict[tuple, EventCandidate] = {}
    for event in sorted(events, key=lambda e: -e.confidence):
        key = (
            event.event_type,
            event.title,
            event.date.to_iso() if event.date else None,
            event.location_name,
        )
        if key in seen:
            continue
        seen[key] = event
    return list(seen.values())
