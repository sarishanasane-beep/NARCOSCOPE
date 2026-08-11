"""Page offset segments for cleaned document text.

Leaf module shared by text cleaning (which builds the segments) and
candidate persistence (which maps evidence offsets back to page
numbers). It imports nothing from the application, so neither side can
create an import cycle through it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PageSegment:
    """Offset range of one page inside the cleaned full text."""

    page_number: int
    start: int
    end: int


def page_for_offset(segments: list[PageSegment], offset: int) -> int | None:
    """Map a cleaned-text offset back to its page number (or None)."""
    for segment in segments:
        if segment.start <= offset < segment.end:
            return segment.page_number
    return None
