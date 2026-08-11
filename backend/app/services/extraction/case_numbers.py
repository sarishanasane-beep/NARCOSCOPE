"""Deterministic case-number extraction.

Uses regex patterns and contextual rules. The original case text, the
normalized case number and evidence are preserved. Cases are never merged
automatically just because numbers look similar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.extraction.spans import TextSpan
from app.utils.text import normalize_case_number

# "Case No. ABC/123/2026", "FIR No. 123/2026", "Crime No. 45/2025"
_CONTEXT_NUMBER = re.compile(
    r"\b(?:Case|FIR|Crime|Cr\.|C\.R\.|Charge\s*Sheet|Complaint|NCB|ED|CBI|DRI)\s*"
    r"(?:No\.?|Number|No)?\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9/._\-]*[0-9][A-Za-z0-9/._\-]*)"
)
# Standalone agency-style tokens: NCB/MUM/123/2026, ABC/123/2026
_AGENCY_TOKEN = re.compile(r"\b[A-Z]{2,6}/(?:[A-Z]{2,6}/)?\d{2,6}/\d{4}\b")
# "CASE-001", "Case-2026-004", "FIR-123"
_LABEL_TOKEN = re.compile(r"\b(?:CASE|FIR|CR|NCB|ED|DRI|CBI)-?[0-9]{2,6}\b", re.IGNORECASE)

_MIN_LENGTH = 4


@dataclass
class CaseNumberCandidate:
    original: str
    normalized: str
    span: TextSpan
    confidence: float = 0.8


def _candidate(match: re.Match) -> CaseNumberCandidate | None:
    # The context pattern captures the actual number in group 1 — the full
    # match includes the label prefix ("Case No. CASE-TEST-001"). Bare
    # patterns (agency tokens, labels) have no capture group, so the whole
    # match is used there. The span keeps the full context for evidence;
    # the normalized number is the clean token without the invented
    # "CASENO." prefix.
    token = match.group(1) if match.lastindex else match.group(0)
    normalized = normalize_case_number(token)
    # A bare "CASE" label without digits is not a case number.
    if len(re.sub(r"[^0-9]", "", normalized)) < 1:
        return None
    if len(normalized) < _MIN_LENGTH:
        return None
    return CaseNumberCandidate(
        original=token,
        normalized=normalized,
        span=TextSpan(start=match.start(), end=match.end(), text=match.group(0)),
    )


def extract_case_numbers(text: str) -> list[CaseNumberCandidate]:
    found: list[CaseNumberCandidate] = []
    for pattern in (_CONTEXT_NUMBER, _AGENCY_TOKEN, _LABEL_TOKEN):
        for match in pattern.finditer(text):
            candidate = _candidate(match)
            if candidate:
                found.append(candidate)
    return _dedupe(found)


def _dedupe(candidates: list[CaseNumberCandidate]) -> list[CaseNumberCandidate]:
    seen: set[tuple[int, int]] = set()
    unique: list[CaseNumberCandidate] = []
    for candidate in sorted(candidates, key=lambda c: (c.span.start, -c.span.length)):
        key = (candidate.span.start, candidate.span.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique
