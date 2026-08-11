"""Deterministic date extraction.

Detects common formats (15 June 2026, 15/06/2026, June 2026, 2026) and
ranges. Stores the normalized date, the original text and a precision
(DAY / MONTH / YEAR / RANGE / UNKNOWN). Missing day/month information is
never fabricated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services.extraction.dictionaries import MONTHS, MONTH_ALTERNATION
from app.services.extraction.spans import TextSpan

DATE_PRECISION_DAY = "DAY"
DATE_PRECISION_MONTH = "MONTH"
DATE_PRECISION_YEAR = "YEAR"
DATE_PRECISION_RANGE = "RANGE"
DATE_PRECISION_UNKNOWN = "UNKNOWN"


@dataclass
class DateInfo:
    normalized: date | None
    original: str
    precision: str
    span: TextSpan

    def to_iso(self) -> str | None:
        return self.normalized.isoformat() if self.normalized else None


_MONTH_DAY_YEAR = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALTERNATION})\s+(\d{{4}})\b", re.IGNORECASE
)
_DAY_MONTH_YEAR = re.compile(
    rf"\b({MONTH_ALTERNATION})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE
)
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_MONTH_YEAR = re.compile(rf"\b({MONTH_ALTERNATION})\s+(\d{{4}})\b", re.IGNORECASE)
_BARE_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

# Ranges
_RANGE_FULL = re.compile(
    rf"\b(?:from|between\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALTERNATION})\s+(\d{{4}})\s+"
    rf"(?:to|and)\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALTERNATION})\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_RANGE_DAY_SPAN = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*[-–—]\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALTERNATION})\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_RANGE_NUMERIC = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*(?:to|and|[-]|[-])\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"
)
_RANGE_DAY_MONTH = re.compile(
    rf"\bbetween\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+and\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"({MONTH_ALTERNATION})\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_RANGE_MONTHS = re.compile(
    rf"\b({MONTH_ALTERNATION})\s+(\d{{4}})\s*(?:to|-|-)\s*({MONTH_ALTERNATION})\s+(\d{{4}})\b",
    re.IGNORECASE,
)


def _parse_numeric(day_part: str, month_part: str, year_part: str) -> date | None:
    """Disambiguate DD/MM vs MM/DD.

    If one component is >12 the other must be the day. Otherwise the
    DD/MM convention is preferred (typical for the source material
    NARCOSCOPE targets).
    """
    a, b = int(day_part), int(month_part)
    if a > 12 and b <= 12:
        day, month = a, b
    elif b > 12 and a <= 12:
        day, month = b, a
    else:
        day, month = a, b
    year = int(year_part)
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_number(name: str) -> int | None:
    return MONTHS.get(name.strip().lower())


def _span_for(match: re.Match) -> TextSpan:
    return TextSpan(start=match.start(), end=match.end(), text=match.group(0))


def extract_dates(text: str) -> list[DateInfo]:
    """Extract all dates from ``text``, most specific first."""
    found: list[DateInfo] = []

    # --- Ranges first (most specific) ---
    for m in _RANGE_FULL.finditer(text):
        try:
            start = date(int(m.group(3)), _month_number(m.group(2)), int(m.group(1)))
            end = date(int(m.group(6)), _month_number(m.group(5)), int(m.group(4)))
        except (ValueError, TypeError):
            continue
        found.append(DateInfo(normalized=start, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
        found.append(DateInfo(normalized=end, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
    for m in _RANGE_DAY_SPAN.finditer(text):
        try:
            start = date(int(m.group(4)), _month_number(m.group(3)), int(m.group(1)))
            end = date(int(m.group(4)), _month_number(m.group(3)), int(m.group(2)))
        except (ValueError, TypeError):
            continue
        found.append(DateInfo(normalized=start, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
        found.append(DateInfo(normalized=end, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
    for m in _RANGE_DAY_MONTH.finditer(text):
        try:
            start = date(int(m.group(4)), _month_number(m.group(3)), int(m.group(1)))
            end = date(int(m.group(4)), _month_number(m.group(3)), int(m.group(2)))
        except (ValueError, TypeError):
            continue
        found.append(DateInfo(normalized=start, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
        found.append(DateInfo(normalized=end, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
    for m in _RANGE_NUMERIC.finditer(text):
        first = _parse_numeric(*m.group(1).replace("-", "/").split("/"))
        second = _parse_numeric(*m.group(2).replace("-", "/").split("/"))
        if first and second:
            found.append(DateInfo(normalized=first, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
            found.append(DateInfo(normalized=second, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
    for m in _RANGE_MONTHS.finditer(text):
        try:
            start = date(int(m.group(2)), _month_number(m.group(1)), 1)
            end = date(int(m.group(4)), _month_number(m.group(3)), 1)
        except (ValueError, TypeError):
            continue
        found.append(DateInfo(normalized=start, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))
        found.append(DateInfo(normalized=end, original=m.group(0), precision=DATE_PRECISION_RANGE, span=_span_for(m)))

    # --- Single dates ---
    for m in _MONTH_DAY_YEAR.finditer(text):
        try:
            normalized = date(int(m.group(3)), _month_number(m.group(2)), int(m.group(1)))
        except (ValueError, TypeError):
            continue
        found.append(DateInfo(normalized=normalized, original=m.group(0), precision=DATE_PRECISION_DAY, span=_span_for(m)))
    for m in _DAY_MONTH_YEAR.finditer(text):
        try:
            normalized = date(int(m.group(3)), _month_number(m.group(1)), int(m.group(2)))
        except (ValueError, TypeError):
            continue
        found.append(DateInfo(normalized=normalized, original=m.group(0), precision=DATE_PRECISION_DAY, span=_span_for(m)))
    for m in _NUMERIC_DATE.finditer(text):
        normalized = _parse_numeric(m.group(1), m.group(2), m.group(3))
        if normalized:
            found.append(DateInfo(normalized=normalized, original=m.group(0), precision=DATE_PRECISION_DAY, span=_span_for(m)))
    for m in _MONTH_YEAR.finditer(text):
        try:
            normalized = date(int(m.group(2)), _month_number(m.group(1)), 1)
        except (ValueError, TypeError):
            continue
        found.append(DateInfo(normalized=normalized, original=m.group(0), precision=DATE_PRECISION_MONTH, span=_span_for(m)))
    for m in _BARE_YEAR.finditer(text):
        normalized = date(int(m.group(0)), 1, 1)
        found.append(DateInfo(normalized=normalized, original=m.group(0), precision=DATE_PRECISION_YEAR, span=_span_for(m)))

    return _dedupe(found)


def _dedupe(dates: list[DateInfo]) -> list[DateInfo]:
    """Drop overlapping lower-priority matches (e.g. MONTH inside DAY).

    The two endpoints of a RANGE share the exact same span — they are
    both kept so a range is never collapsed into a single date.
    """
    dates.sort(key=lambda d: (d.span.start, -(d.span.length)))
    kept: list[DateInfo] = []
    for candidate in dates:
        if any(k.span == candidate.span for k in kept):
            kept.append(candidate)
            continue
        if any(_overlaps(candidate.span, k.span) for k in kept):
            continue
        kept.append(candidate)
    kept.sort(key=lambda d: d.span.start)
    return kept


def _overlaps(a: TextSpan, b: TextSpan) -> bool:
    return a.start < b.end and b.start < a.end
